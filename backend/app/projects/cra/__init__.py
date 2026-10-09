"""CAD Reuse Assistant -- detect missing components and suggest existing parts to reuse.

Status: placeholder. This is where the CRA group's logic starts:
  * routes for the UI in register_routes()
  * reacting to changes in FreeCAD in on_cad_event()
  * read/write CAD via self.ctx.cad
  * LLM agents via self.ctx.ai (model: OLLAMA_MODEL_CRA) -- example in agent.py,
    reachable as POST /api/projects/cra/agent {"message": "..."}
UI: frontend/src/features/cra/
"""

from app.ai.routes import AgentRequest
from app.projects.stub import StubModule


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
