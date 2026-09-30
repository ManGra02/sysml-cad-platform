"""Missing CAD Component Recommendation -- detect missing components and suggest them.

Status: placeholder. This is where the MCR group's logic starts:
  * routes for the UI in register_routes()
  * reacting to changes in FreeCAD in on_cad_event()
  * read/write CAD via self.ctx.cad
UI: frontend/src/features/mcr/
"""

from app.projects.stub import StubModule


class McrModule(StubModule):
    id = "mcr"
    title = "Missing CAD Component Recommendation"
    description = "Detect missing components in the CAD model and suggest matching parts."
    icon = "puzzle"
