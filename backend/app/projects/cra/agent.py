"""The CRA agent -- starting point for LLM support in finding reusable parts.

Read-only: it looks for SysML parts without a CAD counterpart. The part
library search is still to come and will be one more tool here.
"""

from app.ai.tools import cad_tools, sysml_tools

PROMPT = """You are the CAD reuse assistant. The SysML v2 system model defines the parts a product \
needs; the FreeCAD model shows what is modelled already. Use the tools to find physical leaf parts \
that are missing in CAD and describe what an existing part would have to fulfil (attributes, \
requirements). Before describing what a part must fulfil, call sysml_neighbours for it: what it \
connects to, its parent assembly and the requirements inherited from there also constrain it. \
Never guess values. Answer briefly, in the language of the question."""


def build_agent(ctx):
    return ctx.ai.agent(sysml_tools(ctx) + cad_tools(ctx), prompt=PROMPT)
