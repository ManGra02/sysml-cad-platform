"""Was ein Projektmodul ist und was es von der Plattform bekommt.

Ein Projekt (BDS, MCR, ...) ist schlicht ein Python-Paket unter
``app/projects/<id>/``. Es erbt von ``ProjectModule`` und bekommt:

  * eigene HTTP-Routen unter ``/api/projects/<id>/*``      (register_routes)
  * jede Aenderung aus FreeCAD, solange es aktiv ist       (on_cad_event)
  * einen CAD-Zugang, der das Bruecken-Token nie sieht     (ctx.cad)
  * einen Kanal zum Browser, WebSocket-Typen ``<id>.*``    (ctx.publish)

Die Bruecke merkt davon nichts: Fachlogik gehoert hierher, nie nach bridge/.
Namensraum-Regel: alles eines Moduls traegt seine id -- Routen, WS-Typen,
Query-Keys, Frontend-Ordner (src/features/<id>/).
"""

import collections
import json
import logging
import uuid
from urllib.parse import quote

from app import config
from app.bridge_client import BridgeUnavailable

log = logging.getLogger("platform.projects")


class CadError(Exception):
    """Die Bruecke hat mit einem Fehler geantwortet (oder ist nicht erreichbar).

    ``failed_op``: bei einem Vorgang der Index der gescheiterten Operation --
    alles davor wurde zurueckgenommen.
    """

    def __init__(self, status, code, message, detail=None):
        super().__init__("%s: %s" % (code, message))
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
        self.failed_op = detail.get("failedOp") if isinstance(detail, dict) else None


class Ref:
    """Platzhalter fuer ein Objekt, das erst im selben Vorgang angelegt wird.

    FreeCAD benennt bei Kollision um ("Motor" -> "Motor001"); den echten Namen
    liefert ``tx.result.name(ref)`` nach dem Vorgang.
    """

    def __init__(self, alias):
        self.alias = alias

    def __repr__(self):
        return "Ref($%s)" % self.alias


_MISSING = object()


class TransactionResult:
    def __init__(self, raw, refs):
        self.raw = raw
        self.atomic = raw.get("atomic")
        self.results = raw.get("results", [])
        self.revs = raw.get("revs", {})
        self.errors = raw.get("errors", [])
        self.created = {ref: raw.get("created", {}).get(ref.alias) for ref in refs}

    def name(self, ref):
        """Echter Objektname eines im Vorgang angelegten Objekts."""
        return self.created[ref]


class Transaction:
    """Mehrere Aenderungen als EIN Vorgang: ein Undo-Schritt, alles oder nichts.

        async with ctx.cad.transaction("Doc", "BDS: Motor anlegen") as tx:
            m = tx.create("Part::Box", name="Motor", props={"Length": "40 mm"})
            tx.add_property(m, "App::PropertyString", "SysMLId", value=element_id)
        tx.result.name(m)   # -> "Motor" oder "Motor001"

    Gesendet wird beim Verlassen des Blocks in EINER Anfrage. Wirft der Block
    selbst eine Exception, wird nichts gesendet.
    """

    def __init__(self, cad, doc, name=None, strict=True):
        self._cad = cad
        self.doc = doc
        self.name = name
        self.strict = strict
        self.ops = []
        self.refs = []
        self.result = None

    @staticmethod
    def _obj(obj):
        if isinstance(obj, Ref):
            return "$" + obj.alias
        if isinstance(obj, str) and obj:
            return obj
        raise TypeError("Objekt als Name (str) oder Ref erwartet, nicht %r" % (obj,))

    def create(self, type_id, name=None, *, label=None, group=None, props=None):
        ref = Ref("o%d" % len(self.refs))
        op = {"op": "create", "type": type_id, "as": ref.alias}
        if name is not None:
            op["name"] = name
        if label is not None:
            op["label"] = label
        if group is not None:
            op["group"] = self._obj(group)
        if props:
            op["props"] = props
        self.ops.append(op)
        self.refs.append(ref)
        return ref

    def delete(self, obj, force=False):
        self.ops.append({"op": "delete", "obj": self._obj(obj), "force": bool(force)})

    def patch(self, obj, props, if_match=None):
        op = {"op": "patch", "obj": self._obj(obj), "props": props}
        if if_match is not None:
            op["if_match"] = if_match
        self.ops.append(op)

    def set_expression(self, obj, prop, expr):
        """``expr=None`` entfernt die Formel."""
        self.ops.append({"op": "set_expression", "obj": self._obj(obj), "prop": prop, "expr": expr})

    def set_cells(self, sheet, cells=None, aliases=None):
        """``cells={"A1": "40 mm"}``, ``aliases={"A1": "laenge"}``; None leert."""
        op = {"op": "set_cells", "sheet": self._obj(sheet)}
        if cells:
            op["cells"] = cells
        if aliases:
            op["aliases"] = aliases
        self.ops.append(op)

    def add_property(self, obj, type_id, name, *, value=_MISSING, group=None, doc=None):
        op = {"op": "add_property", "obj": self._obj(obj), "type": type_id, "name": name}
        if value is not _MISSING:
            op["value"] = value
        if group is not None:
            op["group"] = group
        if doc is not None:
            op["doc"] = doc
        self.ops.append(op)

    def remove_property(self, obj, name):
        self.ops.append({"op": "remove_property", "obj": self._obj(obj), "name": name})

    async def commit(self):
        if not self.ops:
            self.result = TransactionResult({}, [])
            return self.result
        raw = await self._cad.operations(self.doc, self.ops, name=self.name, strict=self.strict)
        self.result = TransactionResult(raw, self.refs)
        return self.result

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            await self.commit()
        return False


def seg(value):
    """Pfadsegment kodieren -- Objektnamen duerfen beliebiges Unicode enthalten."""
    return quote(value, safe="")


class CadClient:
    """Zugang eines Moduls zum CAD-Modell -- dieselbe API wie der Browser sie sieht.

    Pfade sind relativ zu ``/api/cad``: ``await ctx.cad.get("/documents")``.

    Jede Schreibanfrage traegt eine eigene X-Request-Id. Das Echo in
    ``on_cad_event`` erkennt ``is_own(event)`` -- ohne das schaukelt sich eine
    Synchronisation in beide Richtungen an ihren eigenen Aenderungen auf.
    """

    OWN_HISTORY = 500

    def __init__(self, bridge, module_id):
        self._bridge = bridge
        self._module_id = module_id
        self._own = collections.deque(maxlen=self.OWN_HISTORY)

    async def _call(self, method, path, *, query=None, body=None, request_id=None,
                    if_match=None, timeout=None):
        headers = {"content-type": "application/json"} if body is not None else {}
        if request_id:
            headers["x-request-id"] = request_id
        if if_match is not None:
            headers["if-match"] = '"%d"' % if_match
        if timeout is None:
            timeout = config.READ_TIMEOUT_S if method == "GET" else config.WRITE_TIMEOUT_S
        try:
            status, _content_type, payload = await self._bridge.request(
                method,
                "/api/cad" + path,
                query=query,
                body=json.dumps(body).encode() if body is not None else None,
                headers=headers,
                timeout=timeout,
            )
        except BridgeUnavailable as exc:
            raise CadError(503, "bridge_%s" % exc.state, exc.detail)
        data = json.loads(payload) if payload else None
        if status >= 400:
            error = (data or {}).get("error", {})
            raise CadError(status, error.get("code", "http_%d" % status),
                           error.get("message", ""), error.get("detail"))
        return data

    def _new_request_id(self):
        request_id = "%s:%s" % (self._module_id, uuid.uuid4())
        self._own.append(request_id)
        return request_id

    def is_own(self, event):
        """Stammt dieses Ereignis aus einer Schreibanfrage DIESES Moduls?"""
        origin = event.get("origin") or ""
        return origin.startswith("bridge:") and origin[len("bridge:"):] in self._own

    # -- Bequeme Formen ---------------------------------------------------

    async def get(self, path, **query):
        return await self._call("GET", path, query={k: v for k, v in query.items() if v is not None} or None)

    async def documents(self):
        return await self.get("/documents")

    async def tree(self, doc):
        return await self.get("/documents/%s/tree" % seg(doc))

    async def object(self, doc, name):
        return await self.get("/documents/%s/objects/%s" % (seg(doc), seg(name)))

    async def patch(self, doc, name, changes, if_match=None):
        """Properties setzen -- ein Aufruf ist in FreeCAD genau ein Undo-Schritt."""
        return await self._call(
            "PATCH",
            "/documents/%s/objects/%s" % (seg(doc), seg(name)),
            body=changes,
            request_id=self._new_request_id(),
            if_match=if_match,
        )

    async def cells(self, doc, sheet, cell_range=None):
        """Benutzte Zellen einer Tabelle: {"A1": {content, value, alias}}."""
        return await self.get("/documents/%s/sheets/%s/cells" % (seg(doc), seg(sheet)), range=cell_range)

    def transaction(self, doc, name=None, strict=True):
        """Mehrere Aenderungen als ein Vorgang -- siehe Transaction."""
        return Transaction(self, doc, name, strict)

    async def operations(self, doc, ops, name=None, strict=True):
        """Rohform von transaction(): eine Liste von Operationen senden."""
        body = {"ops": ops, "strict": strict}
        if name:
            body["name"] = name
        return await self._call(
            "POST",
            "/documents/%s/operations" % seg(doc),
            body=body,
            request_id=self._new_request_id(),
            timeout=config.RECOMPUTE_TIMEOUT_S,
        )

    # Kurzformen: je ein Vorgang mit einer Operation.

    async def create(self, doc, type_id, name=None, **kw):
        """Ein Objekt anlegen; liefert den echten Namen."""
        tx = self.transaction(doc)
        ref = tx.create(type_id, name, **kw)
        return (await tx.commit()).name(ref)

    async def delete(self, doc, obj, force=False):
        tx = self.transaction(doc)
        tx.delete(obj, force)
        return await tx.commit()

    async def set_expression(self, doc, obj, prop, expr):
        tx = self.transaction(doc)
        tx.set_expression(obj, prop, expr)
        return await tx.commit()

    async def set_cells(self, doc, sheet, cells=None, aliases=None):
        tx = self.transaction(doc)
        tx.set_cells(sheet, cells, aliases)
        return await tx.commit()

    async def add_property(self, doc, obj, type_id, name, **kw):
        tx = self.transaction(doc)
        tx.add_property(obj, type_id, name, **kw)
        return await tx.commit()

    async def remove_property(self, doc, obj, name):
        tx = self.transaction(doc)
        tx.remove_property(obj, name)
        return await tx.commit()

    async def recompute(self, doc):
        return await self._call(
            "POST",
            "/documents/%s/recompute" % seg(doc),
            request_id=self._new_request_id(),
            timeout=config.RECOMPUTE_TIMEOUT_S,
        )


class ProjectContext:
    """Was ein Modul von der Plattform in die Hand bekommt."""

    def __init__(self, module_id, cad, publish):
        self.module_id = module_id
        self.cad = cad
        self._publish = publish
        self.log = logging.getLogger("platform.projects." + module_id)

    def publish(self, kind, payload=None):
        """Ereignis an alle Browser-Tabs: WebSocket-Typ ``<id>.<kind>``."""
        frame = {"type": "%s.%s" % (self.module_id, kind)}
        if payload:
            frame["data"] = payload
        self._publish(frame)


class ProjectModule:
    """Basisklasse. Alle Haken sind optional; ueberschreiben, was man braucht."""

    #: Kurz, klein, stabil -- steckt in URLs, WS-Typen und Ordnernamen.
    id = ""
    title = ""
    description = ""
    #: Name eines lucide-Icons (https://lucide.dev), z. B. "arrow-left-right"
    icon = "boxes"

    #: Wird von der Registry gesetzt, bevor irgendein Haken laeuft.
    ctx: ProjectContext

    def register_routes(self, router):
        """Eigene Routen an ``router`` haengen (Prefix /api/projects/<id>).

        Reserviert: ``/activate``.
        """

    async def on_activate(self):
        """Das Projekt wurde gewaehlt (auch beim Backend-Start, wenn es aktiv war)."""

    async def on_deactivate(self):
        """Ein anderes Projekt wurde gewaehlt."""

    async def on_cad_event(self, event):
        """Eine Aenderung aus FreeCAD -- nur, solange dieses Projekt aktiv ist.

        ``event`` ist ein Ereignis aus cad_contract.events (cad.changed, doc.opened ...).
        Es traegt nur Identitaet; Werte liest man ueber ``self.ctx.cad`` nach.
        Bei ``cad.resync`` ist der eigene Stand komplett neu aufzubauen.
        """
