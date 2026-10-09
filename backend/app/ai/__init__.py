"""AI adapter -- LLM access and agent building blocks for the project modules.

The platform talks to exactly one provider: Ollama Cloud (https://ollama.com),
authenticated with OLLAMA_API_KEY. Every project module gets its own model,
configured per project id (OLLAMA_MODEL_BDS, OLLAMA_MODEL_CRA, ...):

    config.py       AiConfig -- key, URL, default model, model per project
    client.py       HTTP to Ollama Cloud for status and model list (aiohttp), AiError
    service.py      AiService -- status for the UI, one ProjectAi per module
    project.py      ProjectAi -- what modules get as ``self.ctx.ai``
    agents.py       react_agent(): a small LangGraph tool-calling loop, run()
    tools.py        ready-made LangChain tools over ctx.sysml and ctx.cad
    routes.py       /api/ai/* for the browser

In a module:

    from app.ai.tools import cad_tools, sysml_tools

    agent = self.ctx.ai.agent(sysml_tools(self.ctx) + cad_tools(self.ctx), prompt="...")
    result = await run(agent, "Which parts of EBike Demo have no CAD model?")

The API key stays in the backend; the browser only ever sees /api/ai/status.
"""

from app.ai.client import AiError
from app.ai.config import AiConfig
from app.ai.project import ProjectAi
from app.ai.service import AiService

__all__ = ["AiService", "AiConfig", "AiError", "ProjectAi"]
