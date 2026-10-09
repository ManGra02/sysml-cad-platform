"""HTTP client for Ollama Cloud -- only what the platform itself needs: model list and key check.

Chat requests do not go through here; they run through langchain-ollama's
ChatOllama (project.py), which brings tool calling and streaming.

Errors arrive as ``AiError`` -- the same shape as ``SysmlError`` and ``CadError``:
``status`` (HTTP status the backend answers with), ``code``, ``message``, ``detail``.
"""

import json

import aiohttp

#: The status check must be quick: the header marker polls it.
STATUS_TIMEOUT_S = 10.0


class AiError(Exception):
    def __init__(self, status, code, message, detail=None):
        super().__init__("%s: %s" % (code, message))
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


class OllamaClient:
    def __init__(self, config):
        self.config = config
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json", **self.config.headers()},
                timeout=aiohttp.ClientTimeout(total=STATUS_TIMEOUT_S, sock_connect=5.0),
            )
        return self._session

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _request(self, method, path):
        base = self.config.base_url
        session = await self._get_session()
        try:
            async with session.request(method, base + path) as response:
                return response.status, await response.text()
        except TimeoutError as exc:
            raise AiError(504, "ai_timeout", "Ollama did not answer in time (%s)" % base) from exc
        except (aiohttp.ClientConnectionError, OSError) as exc:
            raise AiError(503, "ai_unreachable", "Ollama not reachable at %s" % base,
                          {"error": str(exc)}) from exc

    async def check_key(self):
        """Is the API key accepted? ollama.com's model list is public, so it can't tell.
        POST /api/me (the account behind the key) answers 401 for a wrong key."""
        status, _ = await self._request("POST", "/api/me")
        if status in (401, 403):
            raise AiError(502, "ai_unauthorized", "Ollama rejected the API key (check OLLAMA_API_KEY)",
                          {"upstreamStatus": status})

    async def list_models(self):
        """Names of the cloud models, e.g. ["gpt-oss:120b", "gpt-oss:20b"]."""
        status, text = await self._request("GET", "/api/tags")
        if status in (401, 403):
            raise AiError(502, "ai_unauthorized", "Ollama rejected the API key (check OLLAMA_API_KEY)",
                          {"upstreamStatus": status})
        if status >= 400:
            raise AiError(502, "ai_upstream_error", "Ollama answered GET /api/tags with HTTP %d" % status,
                          {"upstreamStatus": status, "body": text[:2000]})
        try:
            models = json.loads(text).get("models") or []
        except (ValueError, AttributeError) as exc:
            raise AiError(502, "ai_upstream_error", "Ollama sent an unexpected model list") from exc
        return [m.get("name") or m.get("model") for m in models if isinstance(m, dict)]
