"""Missing CAD Component Recommendation -- fehlende Bauteile erkennen und vorschlagen.

Stand: Platzhalter. Hier beginnt die Logik der MCR-Gruppe:
  * Routen fuer die Oberflaeche in register_routes()
  * Reaktion auf Aenderungen in FreeCAD in on_cad_event()
  * CAD lesen/schreiben ueber self.ctx.cad
Oberflaeche: frontend/src/features/mcr/
"""

from app.projects.stub import StubModule


class McrModule(StubModule):
    id = "mcr"
    title = "Missing CAD Component Recommendation"
    description = "Fehlende Komponenten im CAD-Modell erkennen und passende Bauteile vorschlagen."
    icon = "puzzle"
