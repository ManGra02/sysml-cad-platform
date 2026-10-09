"""/api/ai/* -- the LLM's state for the browser (the header marker).

Project modules do not need these routes: they use ``self.ctx.ai`` directly and
offer their own agent endpoints under /api/projects/<id>/*.
Errors in the platform's usual shape: ``{"error": {"code", "message", "detail"}}``.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.ai.client import AiError


class AgentRequest(BaseModel):
    """Body of a module's ``POST /api/projects/<id>/agent``."""
    message: str


async def _ai_error(_request, exc):
    body = {"code": exc.code, "message": exc.message}
    if exc.detail is not None:
        body["detail"] = exc.detail
    return JSONResponse({"error": body}, status_code=exc.status)


def install(app, service):
    """Mount /api/ai/* and turn every AiError into the platform's error shape."""
    app.add_exception_handler(AiError, _ai_error)
    app.include_router(build_router(service))


def build_router(service):
    router = APIRouter(prefix="/api/ai", tags=["AI"])

    @router.get("/status")
    async def status(refresh: bool = False):
        """Is Ollama configured and reachable, which model does each project use?
        (Not reachable is a normal state.) Cached for OLLAMA_STATUS_TTL_S unless ``refresh``."""
        return await service.status(refresh=refresh)

    return router
