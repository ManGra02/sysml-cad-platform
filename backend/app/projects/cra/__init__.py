"""CAD Reuse Assistant -- an engineering agent that reuses existing parts and finds CAD models.

  * agent.py      the agent (LangGraph): plans, uses tools, a reviewer checks its answer
  * tools.py      its own tools: PLM, understand a part, search, verify, relax a rule, envelope
  * profile.py    understanding a part: what it is and the rules a replacement must meet (LLM)
  * guardrails.py the fixed safety limits around those rules (plain Python)
  * specs.py      reading part names/descriptions into specs (LLM, cached)
  * plm.py        the PLM (Cascadia, read-only), with the attached CAD files
  * session.py    one agent run

Routes: POST /agent {"message"} (any question), POST /find-cad {"item_number"} (mission B),
GET /plm/missing-cad, POST /envelope (create an approved placeholder in FreeCAD).
UI: frontend/src/features/cra/
"""

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.ai.routes import AgentRequest
from app.projects.cra.plm import PlmError
from app.projects.stub import StubModule


class FindCadRequest(BaseModel):
    item_number: str


class EnvelopeRequest(BaseModel):
    """An envelope proposal (from propose_envelope_model) the engineer approved."""
    type: str = Field(pattern=r"^Part::(Box|Cylinder)$")
    props: dict
    label: str = "CRA envelope"
    doc: str | None = None


def _plm_error(exc):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=503)


class CraModule(StubModule):
    id = "cra"
    title = "CAD Reuse Assistant"
    description = "Detect missing components in the CAD model and suggest existing parts to reuse."
    icon = "puzzle"

    def register_routes(self, router):
        super().register_routes(router)

        @router.post("/agent")
        async def agent(body: AgentRequest):
            """Ask the CRA agent anything -> {model, answer, steps, result}."""
            return await self._run(body.message)

        @router.post("/find-cad")
        async def find_cad(body: FindCadRequest):
            """Mission B for one PLM part without CAD -> {model, answer, steps, result}."""
            return await self._run("PLM part %s has no CAD model attached. Find a CAD model for it."
                                   % body.item_number)

        @router.get("/plm/missing-cad")
        async def missing_cad(limit: int = 200):
            """PLM parts without an attached CAD model."""
            from app.projects.cra.session import CraSession

            try:
                return await CraSession(self.ctx).without_cad(limit)
            except PlmError as exc:
                return _plm_error(exc)

        @router.post("/envelope")
        async def envelope(body: EnvelopeRequest):
            """Create an approved placeholder in FreeCAD (active document unless ``doc``)."""
            doc = body.doc or (await self.ctx.cad.documents()).get("active")
            if not doc:
                return JSONResponse({"error": {"code": "no_document", "message": "No FreeCAD document is open"}},
                                    status_code=409)
            name = await self.ctx.cad.create(doc, body.type, "CraEnvelope", label=body.label, props=body.props)
            return {"doc": doc, "name": name}

    async def _run(self, message):
        # Imported on first use: LangChain/LangGraph take seconds to import.
        from app.ai.agents import run
        from app.projects.cra.agent import STEP_LIMIT, build_agent

        try:
            return await run(build_agent(self.ctx), message, model=self.ctx.ai.model, recursion_limit=STEP_LIMIT)
        except PlmError as exc:
            return _plm_error(exc)
