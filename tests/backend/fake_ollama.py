"""In-memory stand-in for Ollama Cloud -- for tests, without key and without network.

Speaks the endpoints the platform uses: POST /api/me (key check), GET /api/tags
(model list) and POST /api/chat (streamed NDJSON, as the ollama client requests
it). Requests without the expected bearer token get 401 -- except the model
list, which is public on ollama.com too.

The chat is scripted: ``replies`` is a list of assistant messages handed out
in order, e.g. first a tool call, then the final answer.
"""

import json

from aiohttp import web


def tool_call(name, **arguments):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def answer(text):
    return {"role": "assistant", "content": text}


class FakeOllama:
    def __init__(self, key="test-key", models=("gpt-oss:120b", "gpt-oss:20b")):
        self.key = key
        self.models = list(models)
        self.replies = []
        self.chats = []     # request bodies of /api/chat
        self.app = web.Application(middlewares=[self._auth])
        self.app.router.add_post("/api/me", self._me)
        self.app.router.add_get("/api/tags", self._tags)
        self.app.router.add_post("/api/chat", self._chat)
        self._runner = None

    async def start(self):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]
        return self.url

    async def stop(self):
        if self._runner is not None:
            await self._runner.cleanup()

    @web.middleware
    async def _auth(self, request, handler):
        if request.path != "/api/tags" and request.headers.get("Authorization") != "Bearer %s" % self.key:
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    async def _me(self, request):
        return web.json_response({"name": "tester"})

    async def _tags(self, request):
        return web.json_response({"models": [{"name": m, "model": m} for m in self.models]})

    async def _chat(self, request):
        body = await request.json()
        self.chats.append(body)
        if body["model"] not in self.models:
            return web.json_response({"error": "model '%s' not found" % body["model"]}, status=404)
        message = self.replies.pop(0) if self.replies else answer("(no scripted reply)")
        chunk = {"model": body["model"], "created_at": "2026-01-01T00:00:00Z", "message": message,
                 "done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}
        response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
        await response.prepare(request)
        await response.write((json.dumps(chunk) + "\n").encode())
        await response.write_eof()
        return response
