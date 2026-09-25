"""Die HTTP-Schicht der Bruecke.

Hier wird FreeCAD nicht angefasst. Ein CI-Grep prueft das; Logging laeuft
ueber freecad_bridge.log, alles am Dokument ueber dispatch() in den
Adapter-Modulen.

Routen dieser Version (M1): nur /api/cad/health und /ws-Geruest. Lesen und
Schreiben folgen in M2/M3.
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
    selection,
    snapshot,
    tree,
    writes,
)
from freecad_bridge import state as bridge_state

#: Lesen ist billig und veraendert nichts -- kurzer Timeout, damit eine
#: beschaeftigte Oberflaeche die UI nicht haengen laesst.
READ_TIMEOUT_S = 5.0

#: Schreiben kann einen Recompute ausloesen (gemessen: 3,88 s fuer eine
#: 25-fach verkettete Cut-Form). Synchron mit Timeout, wie entschieden.
WRITE_TIMEOUT_S = 30.0


def error_response(code, message, status, detail=None, request_id=None):
    """Einheitliche Fehlerhuelle -- nie nackter HTTP-Text.

    Das Frontend soll Fehler typisiert anzeigen koennen; ein Traceback gehoert
    nicht hinein.
    """
    payload = {"error": {"code": code, "message": message}}
    if detail is not None:
        payload["error"]["detail"] = detail
    if request_id:
        payload["error"]["request_id"] = request_id
    return web.json_response(payload, status=status)


@web.middleware
async def security_middleware(request, handler):
    """Host, Origin und Token -- in dieser Reihenfolge.

    Die Host-Pruefung ist die zweite, unabhaengige Verteidigung gegen
    DNS-Rebinding: dort ist die Anfrage same-origin und traegt gar keinen
    Origin, eine Origin-Pruefung hilft also prinzipiell nicht.
    """
    if not auth.host_allowed(request.headers.get("Host")):
        return error_response("forbidden_host", "Unerlaubter Host-Header", 403)

    if not auth.origin_allowed(request.headers.get("Origin")):
        return error_response("forbidden_origin", "Unerlaubte Herkunft", 403)

    state = bridge_state.get_state()
    presented = auth.bearer_from_header(request.headers.get("Authorization"))
    if not auth.token_matches(state.token, presented):
        return error_response(
            "unauthorized",
            "Token fehlt oder ist ungueltig (Authorization: Bearer ...)",
            401,
        )

    return await handler(request)


@web.middleware
async def error_middleware(request, handler):
    """BridgeError in die Fehlerhuelle uebersetzen, alles andere als 500."""
    request_id = request.headers.get("X-Request-Id")
    try:
        return await handler(request)
    except dispatch.BridgeError as exc:
        return error_response(
            exc.code, exc.message, exc.http_status, exc.detail, request_id
        )
    except web.HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - Sicherheitsnetz
        log.error("Unbehandelt: %r" % (exc,), request_id)
        return error_response(
            "internal_error", "Unerwarteter Fehler in der Bruecke", 500,
            type(exc).__name__, request_id,
        )


async def handle_health(request):
    """Antwortet IMMER sofort -- liest nur den Snapshot, dispatcht nie."""
    data = snapshot.read()
    state = bridge_state.get_state()
    data["running"] = bool(state.running)
    data["queue_depth"] = dispatch.queue_depth()
    data["busy"] = data["queue_depth"] > 0
    return web.json_response(data)


def _csv_param(request, name):
    """Komma-getrennter Query-Parameter -> Liste, oder None wenn nicht gesetzt.

    None und [] bedeuten Verschiedenes: 'kein Filter' gegen 'leerer Filter'.
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
    """Batch-Route: mehrere Objekte in EINER Dispatch-Runde.

    Ohne sie braeuchte eine Tabelle mit Property-Spalten N+1 Anfragen.
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
    """Im 3D-Fenster auswaehlen und anfahren.

    Bewusst als READ eingestuft: es aendert die Ansicht, nicht das Dokument,
    und darf deshalb auch waehrend einer offenen Skizzenbearbeitung laufen.
    """
    try:
        body = await request.json()
    except Exception:
        return error_response("bad_request", "JSON-Body erwartet", 400)

    refs = body.get("refs") or []
    zoom = bool(body.get("zoom", True))
    data = await _read(lambda: selection.set_selection(refs, zoom_to_fit=zoom))
    return web.json_response(data)


async def _write(fn, request_id=None):
    return await dispatch.dispatch(
        fn, kind=dispatch.WRITE, timeout=WRITE_TIMEOUT_S, request_id=request_id
    )


async def handle_patch_object(request):
    """Properties setzen -- nur die geaenderten Felder, in EINER Transaktion.

    Body: {"Length": "40 mm", "Label": "Gehaeuse"}  (Vertragsform oder nackter Wert)
    Query: ?recompute=false unterdrueckt den Recompute (dann eigene Route nutzen).
    """
    doc_name = request.match_info["doc"]
    obj_name = request.match_info["name"]
    request_id = request.headers.get("X-Request-Id")
    recompute = request.query.get("recompute", "true").lower() != "false"

    try:
        changes = await request.json()
    except Exception:
        return error_response("bad_request", "JSON-Body erwartet", 400, request_id=request_id)

    data = await _write(
        lambda: writes.patch_object(
            doc_name, obj_name, changes, request_id=request_id, recompute=recompute
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


async def handle_ws(request):
    """WebSocket-Geruest. Ereignisse folgen in M4.

    Der Origin wird VOR accept() geprueft (durch die Middleware, die auch fuer
    diese Route laeuft) und das Token im Authorization-Header verlangt --
    Browser koennen bei new WebSocket() keine Header setzen, damit ist dieser
    Endpunkt fuer Web-Angreifer strukturell unerreichbar.
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
            # Der Bruecken-WS ist server->client. Eingehendes wird ignoriert.
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
    app.router.add_get("/api/cad/types", handle_types)

    app.router.add_get("/api/cad/selection", handle_get_selection)
    app.router.add_put("/api/cad/selection", handle_set_selection)

    app.router.add_get("/ws", handle_ws)
    return app
