"""The CRA agent -- finds SysML parts without a CAD counterpart and the existing part to reuse.

Read-only: it looks for SysML parts without a CAD counterpart and searches the PLM part
library for each of them (find_matching_parts: by function and dimensions, not by name).

Besides the text answer it returns a structured result (MissingParts) that
the UI can show as a table.
"""

from pydantic import BaseModel, Field

from app.ai.tools import cad_tools, calc_tools, progress_tool, sysml_tools
from app.projects.cra.tools import cra_tools

PROMPT = """You are the CAD reuse assistant. The SysML v2 system model defines the parts a product \
needs; the FreeCAD model shows what is modelled already. Use the tools to find physical leaf parts \
that are missing in CAD. For each missing part read its attributes (sysml_attributes) and call \
find_matching_parts with them, exactly as modelled. Put the best part (item number and name) or \
"no suitable part" into the reason, plus the near miss and its failures if nothing fits. \
Use calculate and convert_units for every calculation, and report_progress for longer tasks. \
Never guess values. Answer briefly, in the language of the question."""


class MissingPart(BaseModel):
    sysml_id: str = Field(description="id of the SysML part usage")
    name: str = Field(description="name of the part in the SysML model")
    reason: str = Field(description="why it counts as missing in CAD, and the best existing part to reuse (or none)")


class MissingParts(BaseModel):
    """Physical SysML parts without a CAD counterpart."""
    parts: list[MissingPart] = Field(default_factory=list)


def build_agent(ctx):
    tools = sysml_tools(ctx) + cad_tools(ctx) + calc_tools() + cra_tools(ctx) + [progress_tool(ctx)]
    return ctx.ai.agent(tools, prompt=PROMPT, response_format=MissingParts)
