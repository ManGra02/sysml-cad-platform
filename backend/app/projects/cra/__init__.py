"""CAD Reuse Assistant -- detect missing components and suggest existing parts to reuse.

Status: placeholder. This is where the CRA group's logic starts:
  * routes for the UI in register_routes()
  * reacting to changes in FreeCAD in on_cad_event()
  * read/write CAD via self.ctx.cad
  * LLM agents via self.ctx.ai (model: OLLAMA_MODEL_CRA) -- agent.py,
    reachable as POST /api/projects/cra/agent {"message": "..."}
  * part library search by function and dimensions (matching.py, specs.py, plm.py, finder.py),
    reachable as POST /api/projects/cra/search {"attributes": {...}, "tolerance_pct": 10}
UI: frontend/src/features/cra/
"""

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.ai.routes import AgentRequest
from app.projects.cra.matching import DEFAULT_TOL_PCT, MAX_TOL_PCT
from app.projects.cra.plm import PlmError
from app.projects.stub import StubModule


class SearchRequest(BaseModel):
    """A required part: its SysML attributes as modelled (partType, function, material, sizes ...)."""
    attributes: dict
    tolerance_pct: float = Field(DEFAULT_TOL_PCT, ge=0, le=MAX_TOL_PCT)


class CraModule(StubModule):
    id = "cra"
    title = "CAD Reuse Assistant"
    description = "Detect missing components in the CAD model and suggest existing parts to reuse."
    icon = "puzzle"

    def register_routes(self, router):
        super().register_routes(router)

        @router.post("/agent")
        async def agent(body: AgentRequest):
            """Ask the example agent (agent.py) -> {model, answer, steps}."""
            # Imported on first use: LangChain/LangGraph take seconds to import.
            from app.ai.agents import run
            from app.projects.cra.agent import build_agent

            return await run(build_agent(self.ctx), body.message, model=self.ctx.ai.model)

        @router.post("/search")
        async def search(body: SearchRequest):
            """Best existing PLM part for a required part, by function and dimensions
            -> {best, near_misses, checked, same_function, passed, tolerance_pct}."""
            from app.projects.cra.finder import Finder

            try:
                return await Finder(self.ctx).find(body.attributes, body.tolerance_pct)
            except PlmError as exc:
                return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=503)
