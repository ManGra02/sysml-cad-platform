"""Testaufbau fuer das Backend -- ganz ohne FreeCAD.

Eine nachgebaute Bruecke (MockBridge) spricht dasselbe Protokoll wie die echte:
Token im Authorization-Header, hello beim WebSocket-Verbinden, gebuendelte
Ereignisse mit monotoner seq, Handshake-Datei mit PID. Das Backend laeuft als
echter uvicorn-Server im selben Event-Loop.

Dass das Backend so vollstaendig ohne FreeCAD testbar ist, ist der praktische
Beweis der Entkopplung.
"""

import asyncio
import json
import os
import secrets
import socket
import uuid

import aiohttp
import pytest
import pytest_asyncio
import uvicorn
from aiohttp import web

from cad_contract.version import CONTRACT_VERSION

BROWSER_ORIGIN = "http://127.0.0.1:8000"


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def wait_for(condition, timeout=5.0, interval=0.02):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if condition():
            return True
        await asyncio.sleep(interval)
    raise AssertionError("Bedingung nicht innerhalb von %.1fs erfuellt" % timeout)


class MockBridge:
    """Verhaelt sich nach aussen wie freecad_bridge."""

    def __init__(self, handshake_path):
        self.handshake_path = handshake_path
        self.port = free_port()
        self.token = None
        self.session_id = None
        self.last_seq = 0
        self.contract_version = CONTRACT_VERSION
        self.requests = []
        self._ws = set()
        self._runner = None

    # -- Lebenszyklus -----------------------------------------------------

    async def start(self, new_session=True):
        if new_session:
            self.token = secrets.token_urlsafe(32)
            self.session_id = str(uuid.uuid4())
            self.last_seq = 0

        app = web.Application(middlewares=[self._auth])
        app.router.add_get("/api/cad/health", self._health)
        app.router.add_get("/api/cad/documents", self._documents)
        app.router.add_get("/api/cad/documents/{doc}/objects/{name}", self._object)
        app.router.add_patch("/api/cad/documents/{doc}/objects/{name}", self._patch)
        app.router.add_post("/api/cad/documents/{doc}/recompute", self._recompute)
        app.router.add_get("/ws", self._websocket)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", self.port).start()
        self.write_handshake()

    async def stop(self, remove_handshake=True):
        for ws in list(self._ws):
            await ws.close()
        self._ws.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if remove_handshake and os.path.exists(self.handshake_path):
            os.remove(self.handshake_path)

    def write_handshake(self, pid=None):
        with open(self.handshake_path, "w", encoding="utf-8") as handle:
            json.dump({
                "magic": "sysml-cad-bridge",
                "pid": pid if pid is not None else os.getpid(),
                "host": "127.0.0.1",
                "port": self.port,
                "token": self.token,
                "session_id": self.session_id,
                "contract_version": self.contract_version,
            }, handle)

    # -- Ereignisse -------------------------------------------------------

    @property
    def ws_count(self):
        return len(self._ws)

    async def push(self, events):
        """Wie der Hub der echten Bruecke: seq vergeben, ein Frame pro Batch."""
        stamped = []
        for event in events:
            self.last_seq += 1
            stamped.append(dict(event, seq=self.last_seq, session_id=self.session_id))
        frame = json.dumps({"type": "events", "session_id": self.session_id, "events": stamped})
        for ws in list(self._ws):
            await ws.send_str(frame)
        return stamped

    def happened_while_nobody_listened(self, count):
        """Ereignisse, die niemand empfangen hat (Hub ohne Clients verwirft)."""
        self.last_seq += count

    # -- Handler ----------------------------------------------------------

    @web.middleware
    async def _auth(self, request, handler):
        self.requests.append({
            "method": request.method,
            "path": request.path_qs,
            "headers": dict(request.headers),
        })
        if request.headers.get("Authorization") != "Bearer %s" % self.token:
            return web.json_response({"error": {"code": "unauthorized"}}, status=401)
        return await handler(request)

    async def _health(self, request):
        return web.json_response({"session_id": self.session_id, "last_seq": self.last_seq,
                                  "contract_version": self.contract_version})

    async def _documents(self, request):
        return web.json_response({"documents": [{"name": "Doc", "label": "Doc"}], "active": "Doc"})

    async def _object(self, request):
        return web.json_response({"doc": request.match_info["doc"],
                                  "name": request.match_info["name"],
                                  "query": dict(request.query)})

    async def _patch(self, request):
        return web.json_response({
            "status": "done",
            "received": await request.json(),
            "request_id": request.headers.get("X-Request-Id"),
        })

    async def _recompute(self, request):
        return web.json_response({"status": "done", "recomputed": 3, "errors": []})

    async def _websocket(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        await ws.send_str(json.dumps({
            "type": "hello",
            "session_id": self.session_id,
            "contract_version": self.contract_version,
            "last_seq": self.last_seq,
        }))
        self._ws.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            self._ws.discard(ws)
        return ws


class BrowserClient:
    """Spielt den Browser: eine WebSocket-Verbindung, sammelt alle Frames."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.frames = []
        self._session = None
        self._ws = None
        self._task = None

    async def connect(self, origin=BROWSER_ORIGIN):
        self._session = aiohttp.ClientSession()
        headers = {"Origin": origin} if origin else {}
        self._ws = await self._session.ws_connect(self.base_url + "/ws", headers=headers)
        self._task = asyncio.create_task(self._collect())
        return self

    async def _collect(self):
        async for message in self._ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                self.frames.append(json.loads(message.data))

    def events(self, type_=None):
        flat = [e for f in self.frames if f.get("type") == "events" for e in f["events"]]
        return [e for e in flat if type_ is None or e["type"] == type_]

    def statuses(self):
        return [f["status"] for f in self.frames if f.get("type") == "bridge.status"]

    async def close(self):
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
        if self._session is not None:
            await self._session.close()


@pytest.fixture
def handshake(tmp_path, monkeypatch):
    path = tmp_path / "bridge.json"
    monkeypatch.setenv("BRIDGE_HANDSHAKE", str(path))
    monkeypatch.delenv("BRIDGE_URL", raising=False)
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    return path


@pytest_asyncio.fixture
async def bridge(handshake):
    mock = MockBridge(str(handshake))
    await mock.start()
    yield mock
    await mock.stop()


@pytest_asyncio.fixture
async def backend(handshake):
    """Echter uvicorn-Server mit dem echten Backend."""
    from app.main import create_app

    app = create_app()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    await wait_for(lambda: server.started, timeout=10)

    session = aiohttp.ClientSession(headers={"Origin": BROWSER_ORIGIN})
    base = "http://127.0.0.1:%d" % port

    class Handle:
        url = base
        http = session
        state = app.state

        async def get(self, path, **kw):
            async with session.get(base + path, **kw) as response:
                return response.status, await response.json(content_type=None)

        async def status(self):
            return (await self.get("/api/status"))[1]["bridge"]

    yield Handle()

    await session.close()
    server.should_exit = True
    await task


@pytest_asyncio.fixture
async def browser(backend):
    client = await BrowserClient(backend.url).connect()
    yield client
    await client.close()
