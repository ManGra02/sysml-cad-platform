"""Das Plattform-Backend.

Sitzt zwischen Browser und FreeCAD-Bruecke und ist der einzige Teil, der beide
kennt. Importiert FreeCAD NIE -- das CAD-Modell wird ausschliesslich ueber die
HTTP-Schnittstelle der Bruecke angefasst. Deshalb laeuft dieser Prozess in
einer normalen venv und auch dort, wo FreeCAD gar nicht installiert ist.

Aufgaben:
  1. die Oberflaeche ausliefern
  2. die Verbindung zur Bruecke verwalten (vier Zustaende, Resync)
  3. /api/cad/* an die Bruecke durchreichen -- das Token bleibt hier
  4. einen gebuendelten Ereignisstrom zum Browser liefern
  5. die Projektmodule beherbergen (app/projects/): Registry, aktives
     Projekt, deren Routen unter /api/projects/<id>/* und ihre Fachlogik
"""

import contextlib
import os

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import config
from app.bridge_client import BridgeClient, BridgeUnavailable
from app.events import BrowserHub
from app.projects.registry import ProjectRegistry, UnknownProject
from app.security import LocalOnlyMiddleware
from cad_contract.version import CONTRACT_VERSION

#: Header, die an die Bruecke weitergereicht werden. Alles andere bleibt hier --
#: insbesondere kein Authorization-Header aus dem Browser.
FORWARDED_REQUEST_HEADERS = ("content-type", "x-request-id", "if-match")


def create_app(bridge_client_factory=BridgeClient, project_modules=None):
    hub = BrowserHub()
    registry = None

    def on_events(events):
        hub.publish_events(events)
        registry.on_events(events)  # nur das aktive Projekt bekommt sie

    bridge = bridge_client_factory(on_events=on_events, on_status=hub.publish_status)
    registry = ProjectRegistry(bridge, hub.publish, modules=project_modules)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        await registry.start()
        await bridge.start()
        try:
            yield
        finally:
            await bridge.stop()
            await registry.stop()

    app = FastAPI(
        title="SysML-CAD Platform",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.bridge = bridge
    app.state.hub = hub
    app.state.registry = registry
    # Keine CORSMiddleware -- Begruendung in security.py.
    app.add_middleware(LocalOnlyMiddleware)

    # -- Status ---------------------------------------------------------

    @app.get("/api/status")
    async def status():
        return {
            "backend": {"contract_version": CONTRACT_VERSION, "clients": hub.client_count},
            "frontend": frontend_build_info(),
            "bridge": bridge.status(),
        }

    # -- Projekte ---------------------------------------------------------

    @app.get("/api/projects")
    async def projects():
        return registry.describe()

    @app.post("/api/projects/{project_id}/activate")
    async def activate_project(project_id: str):
        try:
            await registry.activate(project_id)
        except UnknownProject:
            return JSONResponse(
                {"error": {"code": "project_not_found",
                           "message": "Unbekanntes Projekt %r" % project_id}},
                status_code=404,
            )
        return registry.describe()

    registry.mount(app)  # /api/projects/<id>/* der Module

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
                "project": registry.active_id,
            },
        )

    # -- Oberflaeche ------------------------------------------------------

    _mount_frontend(app)
    return app


_PLACEHOLDER = """<!doctype html><html lang="de"><meta charset="utf-8">
<title>SysML-CAD Platform</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h1>SysML-CAD Platform</h1>
<p>Das Backend laeuft. Die Oberflaeche ist noch nicht gebaut:
<code>scripts/setup</code> ausfuehren oder <code>pnpm build</code> im Ordner
<code>frontend/</code>.</p>
<p><a href="/api/status">/api/status</a> &middot; <a href="/api/docs">API-Dokumentation</a></p>
</body></html>"""

#: Vite versieht jede Datei unter assets/ mit einem Inhalts-Hash im Namen --
#: sie aendert sich nie und darf beliebig lange zwischengespeichert werden.
IMMUTABLE = "public, max-age=31536000, immutable"
#: index.html dagegen verweist auf die aktuellen Hash-Namen und muss nach
#: jedem Build neu geholt werden, sonst laedt der Browser eine alte Oberflaeche.
REVALIDATE = "no-cache"


class _HashedAssets(StaticFiles):
    async def check_config(self):
        # Fehlt das Verzeichnis (noch nicht gebaut), ist das kein Serverfehler,
        # sondern schlicht 404 -- Starlette wuerde hier sonst mit 500 abbrechen.
        if os.path.isdir(self.directory):
            await super().check_config()

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def frontend_build_info():
    """Ob und wann die Oberflaeche gebaut wurde -- fuer /api/status und doctor."""
    index = config.STATIC_DIR / "index.html"
    if not index.is_file():
        return {"built": False, "builtAt": None}
    return {"built": True, "builtAt": index.stat().st_mtime}


def _mount_frontend(app):
    # check_dir=False: das Verzeichnis darf beim Start fehlen oder waehrend
    # eines Builds kurz verschwinden. Ein spaeterer Build wird ohne
    # Backend-Neustart ausgeliefert.
    app.mount(
        "/assets",
        _HashedAssets(directory=config.STATIC_DIR / "assets", check_dir=False),
        name="assets",
    )

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
        index = config.STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": REVALIDATE})
        return HTMLResponse(_PLACEHOLDER, headers={"Cache-Control": REVALIDATE})


app = create_app()
