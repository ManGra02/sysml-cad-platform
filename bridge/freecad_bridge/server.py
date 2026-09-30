"""The HTTP layer of the bridge.

FreeCAD is not touched here. A CI grep checks this; logging goes through
freecad_bridge.log, everything involving the document through dispatch() in
the adapter modules.

Routes: health, reading (documents, tree, objects, types), selection,
writing (PATCH with optional If-Match, transactions made of several
operations, recompute), spreadsheet cells and /ws.
"""

import json

from aiohttp import web

from cad_contract.version import CONTRACT_VERSION
from freecad_bridge import (
    auth,
    dispatch,
    documents,
    log,
    objects,
    operations,
    selection,
    snapshot,
    tree,
    writes,
)
from freecad_bridge import state as bridge_state

#: Reading is cheap and changes nothing -- short timeout so that a busy
#: FreeCAD GUI does not leave the UI hanging.
READ_TIMEOUT_S = 5.0

#: Writing can trigger a recompute (measured: 3.88 s for a 25-fold
#: chained Cut shape). Synchronous with a timeout, as decided.
WRITE_TIMEOUT_S = 30.0


def error_response(code, message, status, detail=None, request_id=None):
    """Uniform error envelope -- never bare HTTP text.

    The frontend should be able to display errors by type; a traceback does
    not belong in it.
    """
    payload = {"error": {"code": code, "message": message}}
    if detail is not None:
        payload["error"]["detail"] = detail
    if request_id:
        payload["error"]["request_id"] = request_id
    return web.json_response(payload, status=status)


@web.middleware
async def security_middleware(request, handler):
    """Host, Origin and token -- in that order.

    The Host check is the second, independent defense against DNS
    rebinding: there the request is same-origin and carries no Origin at
    all, so an Origin check cannot help in principle.
    """
    if not auth.host_allowed(request.headers.get("Host")):
        return error_response("forbidden_host", "Host header not allowed", 403)

    if not auth.origin_allowed(request.headers.get("Origin")):
        return error_response("forbidden_origin", "Origin not allowed", 403)

    state = bridge_state.get_state()
    presented = auth.bearer_from_header(request.headers.get("Authorization"))
    if not auth.token_matches(state.token, presented):
        return error_response(
            "unauthorized",
            "Token missing or invalid (Authorization: Bearer ...)",
            401,
        )

    return await handler(request)


@web.middleware
async def error_middleware(request, handler):
    """Translate BridgeError into the error envelope, everything else as 500."""
    request_id = request.headers.get("X-Request-Id")
    try:
        return await handler(request)
    except dispatch.BridgeError as exc:
        return error_response(
            exc.code, exc.message, exc.http_status, exc.detail, request_id
        )
    except web.HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - safety net
        log.error("Unhandled: %r" % (exc,), request_id)
        return error_response(
            "internal_error", "Unexpected error in the bridge", 500,
            type(exc).__name__, request_id,
        )


async def handle_health(request):
    """ALWAYS answers immediately -- only reads the snapshot, never dispatches."""
    data = snapshot.read()
    state = bridge_state.get_state()
    data["running"] = bool(state.running)
    data["queue_depth"] = dispatch.queue_depth()
    data["busy"] = data["queue_depth"] > 0
    return web.json_response(data)


def _csv_param(request, name):
    """Comma-separated query parameter -> list, or None if not set.

    None and [] mean different things: 'no filter' vs. 'empty filter'.
    """
    raw = request.query.get(name)
    if raw is None:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def _include_flags(request):
    include = set(_csv_param(request, "include") or [])
    return {
        "geometry": "geometry" in include,
        "internal": "internal" in include,
    }


async def _read(fn, request_id=None):
    return await dispatch.dispatch(
        fn, kind=dispatch.READ, timeout=READ_TIMEOUT_S, request_id=request_id
    )


async def handle_documents(request):
    data = await _read(documents.list_documents)
    return web.json_response(data)


async def handle_tree(request):
    doc_name = request.match_info["doc"]
    flags = _include_flags(request)
    data = await _read(
        lambda: tree.build_tree(doc_name, include_internal=flags["internal"])
    )
    return web.json_response(data)


async def handle_object_list(request):
    """Batch route: several objects in ONE dispatch round.

    Without it, a table with property columns would need N+1 requests.
    """
    doc_name = request.match_info["doc"]
    names = _csv_param(request, "names")
    fields = _csv_param(request, "fields")
    flags = _include_flags(request)

    data = await _read(
        lambda: objects.list_objects(
            doc_name,
            names=names,
            fields=fields,
            include_geometry=flags["geometry"],
            include_internal=flags["internal"],
        )
    )
    return web.json_response(data)


async def handle_object_detail(request):
    doc_name = request.match_info["doc"]
    obj_name = request.match_info["name"]
    fields = _csv_param(request, "fields")
    flags = _include_flags(request)

    def read_object():
        obj = objects.get_object(doc_name, obj_name)
        return objects.describe_object(
            obj,
            fields=fields,
            include_geometry=flags["geometry"],
            include_internal=flags["internal"],
        )

    return web.json_response(await _read(read_object))


async def handle_types(request):
    return web.json_response(await _read(objects.list_types))


async def handle_get_selection(request):
    return web.json_response(await _read(selection.get_selection))


async def handle_set_selection(request):
    """Select in the 3D view and bring into view.

    Deliberately classified as READ: it changes the view, not the document,
    and may therefore also run while a sketch is open for editing.
    """
    try:
        body = await request.json()
    except Exception:
        return error_response("bad_request", "JSON body expected", 400)

    refs = body.get("refs") or []
    zoom = bool(body.get("zoom", True))
    data = await _read(lambda: selection.set_selection(refs, zoom_to_fit=zoom))
    return web.json_response(data)


async def _write(fn, request_id=None):
    return await dispatch.dispatch(
        fn, kind=dispatch.WRITE, timeout=WRITE_TIMEOUT_S, request_id=request_id
    )


def parse_if_match(value):
    """``If-Match`` -> rev as int, None for no check.

    Accepts ``12``, ``"12"`` and ``W/"12"``; ``*`` means "any state".
    An unreadable value is an error, not a silent skip of the check --
    otherwise a broken client would unnoticeably overwrite others' changes.
    """
    if value is None:
        return None
    text = value.strip()
    if text == "*":
        return None
    if text.startswith("W/"):
        text = text[2:]
    text = text.strip('"')
    try:
        rev = int(text)
    except ValueError:
        raise ValueError(value)
    if rev < 0:
        raise ValueError(value)
    return rev


async def handle_patch_object(request):
    """Set properties -- only the changed fields, in ONE transaction.

    Body: {"Length": "40 mm", "Label": "Housing"}  (contract form or bare value)
    Query: ?recompute=false suppresses the recompute (then use the separate route).
    Header: If-Match: <rev> -- 409 rev_mismatch if the object has changed in
    the meantime.
    """
    doc_name = request.match_info["doc"]
    obj_name = request.match_info["name"]
    request_id = request.headers.get("X-Request-Id")
    recompute = request.query.get("recompute", "true").lower() != "false"
    try:
        if_match = parse_if_match(request.headers.get("If-Match"))
    except ValueError:
        return error_response(
            "bad_request", "If-Match expects a rev (integer)", 400, request_id=request_id
        )

    try:
        changes = await request.json()
    except Exception:
        return error_response("bad_request", "JSON body expected", 400, request_id=request_id)

    data = await _write(
        lambda: writes.patch_object(
            doc_name, obj_name, changes, request_id=request_id, recompute=recompute,
            if_match=if_match,
        ),
        request_id,
    )
    return web.json_response(data)


async def handle_recompute(request):
    doc_name = request.match_info["doc"]
    request_id = request.headers.get("X-Request-Id")
    data = await _write(
        lambda: writes.recompute_document(doc_name, request_id=request_id), request_id
    )
    return web.json_response(data)


async def handle_operations(request):
    """Several changes as ONE transaction (one undo step, all or nothing).

    Body: {"name": "...", "strict": true, "ops": [{"op": "create", ...}, ...]}
    See freecad_bridge/operations.py for the operations.
    """
    doc_name = request.match_info["doc"]
    request_id = request.headers.get("X-Request-Id")
    try:
        body = await request.json()
    except Exception:
        return error_response("bad_request", "JSON body expected", 400, request_id=request_id)
    if not isinstance(body, dict):
        return error_response("bad_request", "JSON object expected", 400, request_id=request_id)

    data = await _write(
        lambda: operations.run(
            doc_name,
            body.get("ops"),
            name=body.get("name"),
            request_id=request_id,
            strict=body.get("strict", True) is not False,
        ),
        request_id,
    )
    return web.json_response(data)


async def handle_cells(request):
    """Used cells of a spreadsheet, optionally ?range=A1:D100."""
    doc_name = request.match_info["doc"]
    sheet_name = request.match_info["sheet"]
    cell_range = request.query.get("range")
    return web.json_response(
        await _read(lambda: operations.read_cells(doc_name, sheet_name, cell_range))
    )


async def handle_ws(request):
    """WebSocket scaffold. Events follow in M4.

    The Origin is checked BEFORE accept() (by the middleware, which also runs
    for this route) and the token is required in the Authorization header --
    browsers cannot set headers with new WebSocket(), so this endpoint is
    structurally unreachable for web attackers.
    """
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    state = bridge_state.get_state()
    await ws.send_str(
        json.dumps(
            {
                "type": "hello",
                "session_id": state.session_id,
                "contract_version": CONTRACT_VERSION,
                "last_seq": state.event_seq,
            }
        )
    )

    request.app["websockets"].add(ws)
    try:
        async for _message in ws:
            # The bridge WS is server->client. Incoming messages are ignored.
            pass
    finally:
        request.app["websockets"].discard(ws)
    return ws


def create_app():
    app = web.Application(middlewares=[error_middleware, security_middleware])
    app["websockets"] = set()
    app.router.add_get("/api/cad/health", handle_health)

    app.router.add_get("/api/cad/documents", handle_documents)
    app.router.add_get("/api/cad/documents/{doc}/tree", handle_tree)
    app.router.add_get("/api/cad/documents/{doc}/objects", handle_object_list)
    app.router.add_get("/api/cad/documents/{doc}/objects/{name}", handle_object_detail)
    app.router.add_patch("/api/cad/documents/{doc}/objects/{name}", handle_patch_object)
    app.router.add_post("/api/cad/documents/{doc}/recompute", handle_recompute)
    app.router.add_post("/api/cad/documents/{doc}/operations", handle_operations)
    app.router.add_get("/api/cad/documents/{doc}/sheets/{sheet}/cells", handle_cells)
    app.router.add_get("/api/cad/types", handle_types)

    app.router.add_get("/api/cad/selection", handle_get_selection)
    app.router.add_put("/api/cad/selection", handle_set_selection)

    app.router.add_get("/ws", handle_ws)
    return app
