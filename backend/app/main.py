"""The platform backend.

Sits between the browser and the FreeCAD bridge and is the only part that
knows both. NEVER imports FreeCAD -- the CAD model is touched exclusively via
the bridge's HTTP interface. That is why this process runs in an ordinary
venv, even where FreeCAD isn't installed at all.

Responsibilities:
  1. serve the UI
  2. manage the connection to the bridge (four states, resync)
  3. pass /api/cad/* through to the bridge -- the token stays here
  4. deliver a batched event stream to the browser
  5. host the project modules (app/projects/): registry, active
     project, their routes under /api/projects/<id>/* and their domain logic
  6. read and write the SysML v2 model (app/sysml/): /api/sysml/* for the
     browser, ctx.sysml for the modules
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
from app.sysml import SysmlService
from app.sysml import routes as sysml_routes
from cad_contract.version import CONTRACT_VERSION

#: Headers that are forwarded to the bridge. Everything else stays here --
#: in particular no Authorization header from the browser.
FORWARDED_REQUEST_HEADERS = ("content-type", "x-request-id", "if-match")


def create_app(bridge_client_factory=BridgeClient, project_modules=None, sysml_service=None):
    hub = BrowserHub()
    sysml = sysml_service or SysmlService()
    registry = None

    def on_events(events):
        hub.publish_events(events)
        registry.on_events(events)  # only the active project receives them

    bridge = bridge_client_factory(on_events=on_events, on_status=hub.publish_status)
    registry = ProjectRegistry(bridge, hub.publish, modules=project_modules, sysml=sysml)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        await sysml.start()
        await registry.start()
        await bridge.start()
        try:
            yield
        finally:
            await bridge.stop()
            await registry.stop()
            await sysml.stop()

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
    app.state.sysml = sysml
    # No CORSMiddleware -- rationale in security.py.
    app.add_middleware(LocalOnlyMiddleware)

    # -- Status ---------------------------------------------------------

    @app.get("/api/status")
    async def status():
        return {
            "backend": {"contract_version": CONTRACT_VERSION, "clients": hub.client_count},
            "frontend": frontend_build_info(),
            "bridge": bridge.status(),
        }

    # -- Projects ---------------------------------------------------------

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
                           "message": "Unknown project %r" % project_id}},
                status_code=404,
            )
        return registry.describe()

    @app.post("/api/projects/deactivate")
    async def deactivate_project():
        await registry.deactivate()
        return registry.describe()

    registry.mount(app)  # the modules' /api/projects/<id>/*

    # -- SysML: the model from the SysML v2 repository -------------------

    sysml_routes.install(app, sysml)  # /api/sysml/*

    # -- CAD: pass-through to the bridge ---------------------------------

    @app.api_route("/api/cad/{path:path}", methods=["GET", "PATCH", "POST", "PUT"])
    async def cad_proxy(path: str, request: Request):
        """Byte proxy. The body is not decoded -- otherwise the bottleneck would
        be the JSON codec (measured 0.35 s for 5.9 MB), not the transport."""
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
                           "detail": {"state": exc.state, "reason": exc.reason}}},
                status_code=503,
            )
        return Response(
            content=payload,
            status_code=status_code,
            media_type=content_type or "application/json",
        )

    # -- Event stream ---------------------------------------------------

    @app.websocket("/ws")
    async def events_socket(websocket: WebSocket):
        # LocalOnlyMiddleware has already checked Origin and Host BEFORE accept().
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

    # -- UI -------------------------------------------------------------

    _mount_frontend(app)
    return app


_PLACEHOLDER = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>SysML-CAD Platform</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h1>SysML-CAD Platform</h1>
<p>The backend is running. The user interface has not been built yet:
run <code>scripts/setup</code> or <code>pnpm build</code> in the
<code>frontend/</code> folder.</p>
<p><a href="/api/status">/api/status</a> &middot; <a href="/api/docs">API documentation</a></p>
</body></html>"""

#: Vite puts a content hash into the name of every file under assets/ --
#: it never changes and may be cached indefinitely.
IMMUTABLE = "public, max-age=31536000, immutable"
#: index.html, on the other hand, refers to the current hashed names and must
#: be re-fetched after every build, otherwise the browser loads a stale UI.
REVALIDATE = "no-cache"


class _HashedAssets(StaticFiles):
    async def check_config(self):
        # If the directory is missing (not built yet), that is not a server
        # error but simply a 404 -- Starlette would otherwise fail with a 500 here.
        if os.path.isdir(self.directory):
            await super().check_config()

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def frontend_build_info():
    """Whether and when the UI was built -- for /api/status and doctor."""
    index = config.STATIC_DIR / "index.html"
    if not index.is_file():
        return {"built": False, "builtAt": None}
    return {"built": True, "builtAt": index.stat().st_mtime}


def _mount_frontend(app):
    # check_dir=False: the directory may be missing at startup or briefly
    # disappear during a build. A later build is served without restarting
    # the backend.
    app.mount(
        "/assets",
        _HashedAssets(directory=config.STATIC_DIR / "assets", check_dir=False),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """SPA catch-all for TanStack Router's browser history.

        Serves ONLY index.html and never puts the path into a file name:
        Path('static') / 'C:/Windows/win.ini' yields C:/Windows/win.ini
        on Windows.
        """
        if full_path.startswith("api/"):
            return JSONResponse(
                {"error": {"code": "not_found", "message": "Unknown API route"}},
                status_code=404,
            )
        index = config.STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": REVALIDATE})
        return HTMLResponse(_PLACEHOLDER, headers={"Cache-Control": REVALIDATE})


app = create_app()
