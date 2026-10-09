"""What a project module is and what it gets from the platform.

A project (BDS, CRA, ...) is simply a Python package under
``app/projects/<id>/``. It inherits from ``ProjectModule`` and gets:

  * its own HTTP routes under ``/api/projects/<id>/*``     (register_routes)
  * every change from FreeCAD, as long as it is active     (on_cad_event)
  * CAD access that never sees the bridge token            (ctx.cad)
  * the SysML v2 model, in the common engineering model    (ctx.sysml)
  * a channel to the browser, WebSocket types ``<id>.*``   (ctx.publish)

The bridge knows nothing about this: domain logic belongs here, never in bridge/.
Namespace rule: everything of a module carries its id -- routes, WS types,
query keys, frontend folder (src/features/<id>/).
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
    """The bridge responded with an error (or is unreachable).

    ``failed_op``: for a transaction, the index of the failed operation --
    everything before it was rolled back.
    """

    def __init__(self, status, code, message, detail=None):
        super().__init__("%s: %s" % (code, message))
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
        self.failed_op = detail.get("failedOp") if isinstance(detail, dict) else None


class Ref:
    """Placeholder for an object that is only created in the same transaction.

    FreeCAD renames on collision ("Motor" -> "Motor001"); ``tx.result.name(ref)``
    returns the actual name after the transaction.
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
        """Actual object name of an object created in the transaction."""
        return self.created[ref]


class Transaction:
    """Several changes as ONE transaction: one undo step, all or nothing.

        async with ctx.cad.transaction("Doc", "BDS: create motor") as tx:
            m = tx.create("Part::Box", name="Motor", props={"Length": "40 mm"})
            tx.add_property(m, "App::PropertyString", "SysMLId", value=element_id)
        tx.result.name(m)   # -> "Motor" or "Motor001"

    Everything is sent in ONE request when the block is exited. If the block
    itself raises an exception, nothing is sent.
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
        raise TypeError("Object expected as name (str) or Ref, not %r" % (obj,))

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
        """``expr=None`` removes the expression."""
        self.ops.append({"op": "set_expression", "obj": self._obj(obj), "prop": prop, "expr": expr})

    def set_cells(self, sheet, cells=None, aliases=None):
        """``cells={"A1": "40 mm"}``, ``aliases={"A1": "length"}``; None clears."""
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
    """Encode a path segment -- object names may contain arbitrary Unicode."""
    return quote(value, safe="")


class CadClient:
    """A module's access to the CAD model -- the same API the browser sees.

    Paths are relative to ``/api/cad``: ``await ctx.cad.get("/documents")``.

    Every write request carries its own X-Request-Id. ``is_own(event)``
    recognizes the echo in ``on_cad_event`` -- without it, a bidirectional
    synchronization would feed back on its own changes.
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
        """Does this event stem from a write request of THIS module?"""
        origin = event.get("origin") or ""
        return origin.startswith("bridge:") and origin[len("bridge:"):] in self._own

    # -- Convenience forms ------------------------------------------------

    async def get(self, path, **query):
        return await self._call("GET", path, query={k: v for k, v in query.items() if v is not None} or None)

    async def documents(self):
        return await self.get("/documents")

    async def tree(self, doc):
        return await self.get("/documents/%s/tree" % seg(doc))

    async def object(self, doc, name):
        return await self.get("/documents/%s/objects/%s" % (seg(doc), seg(name)))

    async def patch(self, doc, name, changes, if_match=None):
        """Set properties -- one call is exactly one undo step in FreeCAD."""
        return await self._call(
            "PATCH",
            "/documents/%s/objects/%s" % (seg(doc), seg(name)),
            body=changes,
            request_id=self._new_request_id(),
            if_match=if_match,
        )

    async def cells(self, doc, sheet, cell_range=None):
        """Used cells of a spreadsheet: {"A1": {content, value, alias}}."""
        return await self.get("/documents/%s/sheets/%s/cells" % (seg(doc), seg(sheet)), range=cell_range)

    def transaction(self, doc, name=None, strict=True):
        """Several changes as one transaction -- see Transaction."""
        return Transaction(self, doc, name, strict)

    async def operations(self, doc, ops, name=None, strict=True):
        """Raw form of transaction(): send a list of operations."""
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

    # Shorthands: one transaction with a single operation each.

    async def create(self, doc, type_id, name=None, **kw):
        """Create an object; returns the actual name."""
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
    """What a module is handed by the platform.

    ``sysml`` is the platform's SysmlService (app/sysml/service.py), shared by all
    modules: ``snap = await self.ctx.sysml.snapshot("EBike Demo")``.

    ``ai`` is this module's ProjectAi (app/ai/project.py), bound to the module's own
    model (OLLAMA_MODEL_<ID>): ``llm = self.ctx.ai.chat_model()`` or
    ``agent = self.ctx.ai.agent(sysml_tools(self.ctx), prompt="...")``.
    """

    def __init__(self, module_id, cad, publish, sysml=None, ai=None):
        self.module_id = module_id
        self.cad = cad
        self.sysml = sysml
        self.ai = ai
        self._publish = publish
        self.log = logging.getLogger("platform.projects." + module_id)

    def publish(self, kind, payload=None):
        """Event to all browser tabs: WebSocket type ``<id>.<kind>``."""
        frame = {"type": "%s.%s" % (self.module_id, kind)}
        if payload:
            frame["data"] = payload
        self._publish(frame)


class ProjectModule:
    """Base class. All hooks are optional; override what you need."""

    #: Short, lowercase, stable -- ends up in URLs, WS types and folder names.
    id = ""
    title = ""
    description = ""
    #: Name of a lucide icon (https://lucide.dev), e.g. "arrow-left-right"
    icon = "boxes"

    #: Set by the registry before any hook runs.
    ctx: ProjectContext

    def register_routes(self, router):
        """Attach your own routes to ``router`` (prefix /api/projects/<id>).

        Reserved: ``/activate``.
        """

    async def on_activate(self):
        """The project was selected (also on backend start, if it was active)."""

    async def on_deactivate(self):
        """Another project was selected, or the project was closed."""

    async def on_cad_event(self, event):
        """A change from FreeCAD -- only while this project is active.

        ``event`` is an event from cad_contract.events (cad.changed, doc.opened ...).
        It carries identity only; read the values via ``self.ctx.cad``.
        On ``cad.resync`` the module's own state has to be rebuilt from scratch.
        """
