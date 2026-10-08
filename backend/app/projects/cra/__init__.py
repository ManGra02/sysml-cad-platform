"""CAD Reuse Assistant -- detect missing components and suggest existing parts to reuse.

Status: placeholder. This is where the CRA group's logic starts:
  * routes for the UI in register_routes()
  * reacting to changes in FreeCAD in on_cad_event()
  * read/write CAD via self.ctx.cad
UI: frontend/src/features/cra/
"""

from app.projects.stub import StubModule


class CraModule(StubModule):
    id = "cra"
    title = "CAD Reuse Assistant"
    description = "Detect missing components in the CAD model and suggest existing parts to reuse."
    icon = "puzzle"
