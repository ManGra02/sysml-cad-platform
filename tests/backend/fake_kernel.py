"""In-memory stand-in for Jupyter with the SysML v2 Pilot kernel -- for the import tests.

Speaks the part of Jupyter's REST and websocket API that app/sysml/importer.py uses and
answers the cells like the real kernel (texts as printed by jupyter-sysml-kernel 0.60.1):

    %repo <url>        prints the url and remembers it
    <.sysml text>      "Package <Name> (<id>)", or "ERROR:..." if the text contains "!!"
    %publish -d --project="<name>" <Package>
                       creates the project in the FakeFlexo it is given (over HTTP) and
                       commits one Package element, then prints what the real kernel prints

It parses nothing: the package name is taken from the %publish line.
"""

import re
import uuid

import aiohttp
from aiohttp import WSMsgType, web


class FakeKernel:
    def __init__(self, flexo, token="sysmlcad"):
        self.flexo = flexo            # a started fake_flexo.FakeFlexo
        self.token = token
        self.repo = None
        self.report_target = None     # set to make %publish report another API base path
        self.kernels = set()
        self.cells = []
        app = web.Application()
        app.router.add_get("/api/status", self._status)
        app.router.add_post("/api/kernels", self._start)
        app.router.add_delete("/api/kernels/{k}", self._shutdown)
        app.router.add_get("/api/kernels/{k}/channels", self._channels)
        self.app = app
        self._runner = None

    async def start(self):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]
        return self.url

    async def stop(self):
        await self._runner.cleanup()

    def _authorized(self, request):
        return request.headers.get("Authorization") == "token " + self.token

    async def _status(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden()
        return web.json_response({"started": "now"})

    async def _start(self, request):
        if not self._authorized(request):
            raise web.HTTPForbidden()
        assert (await request.json())["name"] == "sysml"
        kid = str(uuid.uuid4())
        self.kernels.add(kid)
        return web.json_response({"id": kid, "name": "sysml"}, status=201)

    async def _shutdown(self, request):
        self.kernels.discard(request.match_info["k"])
        return web.Response(status=204)

    async def _channels(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                break
            req = msg.json()
            code = req["content"]["code"]
            self.cells.append(code)
            parent = {"msg_id": req["header"]["msg_id"]}
            text = await self._execute(code)
            await ws.send_json({"msg_type": "status", "parent_header": parent, "content": {"execution_state": "busy"}})
            if text:
                await ws.send_json({"msg_type": "stream", "parent_header": parent,
                                    "content": {"name": "stdout", "text": text}})
            await ws.send_json({"msg_type": "execute_reply", "parent_header": parent, "content": {"status": "ok"}})
            await ws.send_json({"msg_type": "status", "parent_header": parent, "content": {"execution_state": "idle"}})
        return ws

    async def _execute(self, code):
        if code.startswith("%repo "):
            self.repo = code.split(None, 1)[1].strip()
            return self.repo + "\n"
        m = re.match(r'%publish -d --project="([^"]*)" (\S+)$', code)
        if m:
            name, package = m.groups()
            async with aiohttp.ClientSession() as http:   # posts to Flexo over HTTP, like the real kernel
                async with http.post(self.flexo.url + "/projects", json={"name": name}) as r:
                    project = await r.json()
                change = [{"identity": {"@id": str(uuid.uuid4())},
                           "payload": {"@type": "Package", "declaredName": package.strip("'")}}]
                async with http.post(self.flexo.url + "/projects/%s/commits" % project["@id"],
                                     json={"@type": "Commit", "change": change}) as r:
                    commit = (await r.json())["@id"]
            return ("API base path: %s\nProcessing..\nPosting commit. Additions: 1, Deletions: 0, "
                    "Modified elements: 0\nSuccessfully posted commit: %s on branch: (Initial) %s\n\n"
                    "Saved to Project %s (%s)\n"
                    % (self.report_target or self.repo, commit, project["defaultBranch"]["@id"], name, project["@id"]))
        if "!!" in code:
            return "ERROR:no viable alternative at input '!!' (2.sysml line : 3 column : 5)\n"
        return "Package Something (%s)\n" % uuid.uuid4()
