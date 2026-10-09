"""The AI side of the platform: status for the UI, one ``ctx.ai`` per project module.

Like the SysML repository, Ollama is a service that comes and goes: "not
configured" and "not reachable" are normal states reported by /api/ai/status --
everything that does not need the LLM keeps working.
"""

import asyncio
import time

from app.ai.client import AiError, OllamaClient
from app.ai.config import AiConfig
from app.ai.project import ProjectAi


def model_available(model, names):
    """Ollama treats "name" and "name:latest" as the same model."""
    def norm(name):
        return name if ":" in name else name + ":latest"
    return norm(model) in {norm(n) for n in names if n}


class AiService:
    def __init__(self, config=None, client=None):
        self.config = config or AiConfig.from_env()
        self.client = client or OllamaClient(self.config)
        self._projects = {}        # module id -> ProjectAi
        self._status = None
        self._checked_at = 0.0
        self._lock = asyncio.Lock()

    async def start(self):
        """Nothing to connect: Ollama is asked on demand."""

    async def stop(self):
        await self.client.close()

    def for_project(self, module_id):
        """The ``ctx.ai`` of one module (the registry calls this once per module)."""
        if module_id not in self._projects:
            self._projects[module_id] = ProjectAi(module_id, self.config)
        return self._projects[module_id]

    # -- Status -----------------------------------------------------------

    async def status(self, refresh=False):
        """Cached for ``status_ttl_s``: the header marker in every tab polls this."""
        async with self._lock:
            now = time.monotonic()
            if refresh or self._status is None or now - self._checked_at >= self.config.status_ttl_s:
                self._status = await self._check()
                self._checked_at = now
            return self._status

    async def _check(self):
        cfg = self.config
        base = {"provider": "ollama-cloud", "url": cfg.base_url, "configured": cfg.configured,
                "checkedAt": time.time()}
        projects = {mid: {"model": cfg.model_for(mid)} for mid in self._projects}
        if not cfg.configured:
            return {**base, "reachable": False, "code": "ai_not_configured",
                    "message": "OLLAMA_API_KEY is not set", "projects": projects}
        try:
            await self.client.check_key()
            names = await self.client.list_models()
        except AiError as exc:
            return {**base, "reachable": False, "code": exc.code, "message": exc.message,
                    "projects": projects}
        for entry in projects.values():
            entry["available"] = bool(entry["model"]) and model_available(entry["model"], names)
        return {**base, "reachable": True, "models": sorted(names), "projects": projects}
