"""Bi-Directional Synchronization -- keep the SysML v2 model and the CAD model in sync.

Status: placeholder. This is where the BDS group's logic starts:
  * routes for the UI in register_routes()
  * reacting to changes in FreeCAD in on_cad_event()
    (own writes are detected by self.ctx.cad.is_own(event))
  * read/write CAD via self.ctx.cad
UI: frontend/src/features/bds/
"""

from app.projects.stub import StubModule


class BdsModule(StubModule):
    id = "bds"
    title = "Bi-Directional Synchronization"
    description = "Keep the SysML v2 system model and the CAD model in sync in both directions."
    icon = "arrow-left-right"
