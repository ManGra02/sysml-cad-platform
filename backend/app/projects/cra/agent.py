"""The CRA agent -- starting point for LLM support in finding reusable parts.

Read-only: it looks for SysML parts without a CAD counterpart. The part
library search is still to come and will be one more tool here.

Besides the text answer it returns a structured result (MissingParts) that
the UI can show as a table.
"""

from pydantic import BaseModel, Field

from app.ai.tools import cad_tools, calc_tools, progress_tool, sysml_tools

PROMPT = """You are the CAD reuse assistant. The SysML v2 system model defines the parts a product \
needs; the FreeCAD model shows what is modelled already. Use the tools to find physical leaf parts \
that are missing in CAD and describe what an existing part would have to fulfil (attributes, \
requirements). Before describing what a part must fulfil, call sysml_neighbours for it: what it \
connects to, its parent assembly and the requirements inherited from there also constrain it. \
Use calculate and convert_units for every calculation, and report_progress for longer tasks. \
Never guess values. Answer briefly, in the language of the question."""


class MissingPart(BaseModel):
    sysml_id: str = Field(description="id of the SysML part usage")
    name: str = Field(description="name of the part in the SysML model")
    reason: str = Field(description="why it counts as missing in CAD, and what a reused part must fulfil")


class MissingParts(BaseModel):
    """Physical SysML parts without a CAD counterpart."""
    parts: list[MissingPart] = Field(default_factory=list)


def build_agent(ctx):
    tools = sysml_tools(ctx) + cad_tools(ctx) + calc_tools() + [progress_tool(ctx)]
    return ctx.ai.agent(tools, prompt=PROMPT, response_format=MissingParts)
