"""Das Plattform-Backend.

Sitzt zwischen Browser und FreeCAD-Bruecke und ist der einzige Teil, der beide
kennt. Importiert FreeCAD NIE -- das CAD-Modell wird ausschliesslich ueber die
HTTP-Schnittstelle der Bruecke angefasst. Deshalb laeuft dieser Prozess in
einer normalen venv und auch dort, wo FreeCAD gar nicht installiert ist.

Aufgaben in M5 (Geruest):
  1. die Oberflaeche ausliefern
  2. die Verbindung zur Bruecke verwalten (vier Zustaende, Resync)
  3. /api/cad/* an die Bruecke durchreichen -- das Token bleibt hier
  4. einen gebuendelten Ereignisstrom zum Browser liefern
Spaeter: Projekt-Registry (M7) und die Fachlogik der Projektmodule.
"""

import contextlib

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import config
from app.bridge_client import BridgeClient, BridgeUnavailable
from app.events import BrowserHub
from app.security import LocalOnlyMiddleware
from cad_contract.version import CONTRACT_VERSION

#: Header, die an die Bruecke weitergereicht werden. Alles andere bleibt hier --
#: insbesondere kein Authorization-Header aus dem Browser.
FORWARDED_REQUEST_HEADERS = ("content-type", "x-request-id", "if-match")


def create_app(bridge_client_factory=BridgeClient):
    hub = BrowserHub()
    bridge = bridge_client_factory(
        on_events=hub.publish_events,
        on_status=hub.publish_status,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        await bridge.start()
        try:
            yield
        finally:
            await bridge.stop()

    app = FastAPI(
        title="SysML-CAD Platform",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.bridge = bridge
    app.state.hub = hub
    # Keine CORSMiddleware -- Begruendung in security.py.
    app.add_middleware(LocalOnlyMiddleware)

    # -- Status ---------------------------------------------------------

    @app.get("/api/status")
    async def status():
        return {
            "backend": {"contract_version": CONTRACT_VERSION, "clients": hub.client_count},
            "bridge": bridge.status(),
        }

    # -- CAD: Durchreichen an die Bruecke --------------------------------

    @app.api_route("/api/cad/{path:path}", methods=["GET", "PATCH", "POST", "PUT"])
    async def cad_proxy(path: str, request: Request):
        """Byte-Proxy. Der Body wird nicht dekodiert -- der Engpass waere sonst
        der JSON-Codec (gemessen 0,35 s fuer 5,9 MB), nicht der Transport."""
        raw_path = request.scope.get("raw_path") or request.url.path.encode()
        target = raw_path.decode("latin-1")

        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() in FORWARDED_REQUEST_HEADERS
        }
        body = await request.body() if request.method != "GET" else None

        if request.method == "GET":
            timeout = config.READ_TIMEOUT_S
        elif target.endswith("/recompute"):
            timeout = config.RECOMPUTE_TIMEOUT_S
        else:
            timeout = config.WRITE_TIMEOUT_S

        try:
            status_code, content_type, payload = await bridge.request(
                request.method,
                target,
                query=request.url.query or None,
                body=body,
                headers=headers,
                timeout=timeout,
            )
        except BridgeUnavailable as exc:
            return JSONResponse(
                {"error": {"code": "bridge_%s" % exc.state, "message": exc.detail,
                           "detail": {"state": exc.state}}},
                status_code=503,
            )
        return Response(
            content=payload,
            status_code=status_code,
            media_type=content_type or "application/json",
        )

    # -- Ereignisstrom --------------------------------------------------

    @app.websocket("/ws")
    async def events_socket(websocket: WebSocket):
        # Origin und Host hat LocalOnlyMiddleware bereits VOR accept() geprueft.
        await websocket.accept()
        await hub.serve(
            websocket,
            {
                "type": "hello",
                "contract_version": CONTRACT_VERSION,
                "bridge": bridge.status(),
            },
        )

    # -- Oberflaeche ------------------------------------------------------

    _mount_frontend(app)
    return app


_PLACEHOLDER = """<!doctype html><html lang="de"><meta charset="utf-8">
<title>SysML-CAD Platform</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h1>SysML-CAD Platform</h1>
<p>Das Backend laeuft. Die Oberflaeche ist noch nicht gebaut
(<code>pnpm build</code> im Ordner <code>frontend/</code>).</p>
<p><a href="/api/status">/api/status</a> &middot; <a href="/api/docs">API-Dokumentation</a></p>
</body></html>"""


def _mount_frontend(app):
    index = config.STATIC_DIR / "index.html"
    assets = config.STATIC_DIR / "assets"

    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """SPA-Catch-all fuer TanStack Routers Browser-History.

        Liefert NUR index.html und setzt den Pfad nie in einen Dateinamen ein:
        Path('static') / 'C:/Windows/win.ini' ergibt unter Windows
        C:/Windows/win.ini.
        """
        if full_path.startswith("api/"):
            return JSONResponse(
                {"error": {"code": "not_found", "message": "Unbekannte API-Route"}},
                status_code=404,
            )
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(_PLACEHOLDER)


app = create_app()
