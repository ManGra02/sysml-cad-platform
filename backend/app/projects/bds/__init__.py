"""Bi-Directional Synchronization -- SysML-v2-Modell und CAD-Modell synchron halten.

Stand: Platzhalter. Hier beginnt die Logik der BDS-Gruppe:
  * Routen fuer die Oberflaeche in register_routes()
  * Reaktion auf Aenderungen in FreeCAD in on_cad_event()
    (eigene Schreibvorgaenge erkennt self.ctx.cad.is_own(event))
  * CAD lesen/schreiben ueber self.ctx.cad
Oberflaeche: frontend/src/features/bds/
"""

from app.projects.stub import StubModule


class BdsModule(StubModule):
    id = "bds"
    title = "Bi-Directional Synchronization"
    description = "SysML-v2-Systemmodell und CAD-Modell in beide Richtungen synchron halten."
    icon = "arrow-left-right"
