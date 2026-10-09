"""Bi-Directional Synchronization -- keep the SysML v2 model and the CAD model in sync.

Status: placeholder. This is where the BDS group's logic starts:
  * routes for the UI in register_routes()
  * reacting to changes in FreeCAD in on_cad_event()
    (own writes are detected by self.ctx.cad.is_own(event))
  * read/write CAD via self.ctx.cad
  * LLM agents via self.ctx.ai (model: OLLAMA_MODEL_BDS) -- example in agent.py,
    reachable as POST /api/projects/bds/agent {"message": "..."}
UI: frontend/src/features/bds/
"""

from app.ai.routes import AgentRequest
from app.projects.stub import StubModule


class BdsModule(StubModule):
    id = "bds"
    title = "Bi-Directional Synchronization"
    description = "Keep the SysML v2 system model and the CAD model in sync in both directions."
    icon = "arrow-left-right"

    def register_routes(self, router):
        super().register_routes(router)

        @router.post("/agent")
        async def agent(body: AgentRequest):
            """Ask the example agent (agent.py) -> {model, answer, steps}."""
            # Imported on first use: LangChain/LangGraph take seconds to import.
            from app.ai.agents import run
            from app.projects.bds.agent import build_agent

            return await run(build_agent(self.ctx), body.message, model=self.ctx.ai.model)
