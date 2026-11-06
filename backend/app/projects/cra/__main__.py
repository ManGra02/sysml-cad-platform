"""Run the CRA agent from the terminal -- real PLM, real LLM, no browser needed.

    cd backend
    uv run python -m app.projects.cra "PLM part PUC-9008 has no CAD model attached. Find a CAD model for it."

SysML and FreeCAD tools are not connected here (they answer with an error, the agent
works around them); for those, use the platform UI.
"""

import asyncio
import json
import sys
from types import SimpleNamespace

from app.ai.agents import run
from app.ai.config import AiConfig
from app.ai.project import ProjectAi
from app.projects.cra.agent import STEP_LIMIT, build_agent


async def main(message):
    ai = ProjectAi("cra", AiConfig.from_env())
    ctx = SimpleNamespace(ai=ai, sysml=None, cad=None, publish=lambda *a, **k: None)
    out = await run(build_agent(ctx), message, model=ai.model, recursion_limit=STEP_LIMIT)
    for i, step in enumerate(out["steps"], 1):
        print("%2d. %s %s" % (i, step["tool"], json.dumps(step["args"], ensure_ascii=False)))
    print("\n--- answer ---\n" + out["answer"])
    print("\n--- result ---\n" + json.dumps(out.get("result"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "Which PLM parts have no CAD model? Find a CAD model for the first fastener."))
