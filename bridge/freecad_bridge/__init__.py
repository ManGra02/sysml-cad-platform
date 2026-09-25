"""Die CAD-Bruecke: lokaler Dienst, der das FreeCAD-Modell bereitstellt.

ENTWURFSREGEL: Alles, was die FreeCAD-API nicht anfasst, gehoert hier NICHT
hinein. Keine Fachlogik, keine Projekt-Registry, keine SPA-Auslieferung, kein
Proxy. Jede Aenderung hier kostet einen FreeCAD-Neustart, jede Aenderung im
Backend eine Sekunde.
"""
