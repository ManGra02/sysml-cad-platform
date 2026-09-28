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
    """Die Bruecke hat mit einem Fehler geantwortet (oder ist nicht erreichbar)."""

    def __init__(self, status, code, message, detail=None):
        super().__init__("%s: %s" % (code, message))
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


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
