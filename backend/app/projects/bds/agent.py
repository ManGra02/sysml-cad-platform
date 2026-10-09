"""The BDS agent -- starting point for LLM support in the synchronization.

Read-only for now: it compares the SysML model with the CAD model and explains
differences. Writing tools (cad_tools(ctx, write=True)) belong behind an explicit
confirmation in the UI.
"""

from app.ai.tools import cad_tools, sysml_tools

PROMPT = """You support the bi-directional synchronization between a SysML v2 system model \
and a FreeCAD CAD model. Use the tools to read both models; never guess values. \
When you compare, name the SysML element and the CAD object, both values with units, \
and the SysML commit (version) you read. Answer briefly, in the language of the question."""


def build_agent(ctx):
    return ctx.ai.agent(sysml_tools(ctx) + cad_tools(ctx), prompt=PROMPT)
