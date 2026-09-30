"""The CAD bridge: a local service that exposes the FreeCAD model.

DESIGN RULE: Anything that does not touch the FreeCAD API does NOT belong
here. No domain logic, no project registry, no SPA serving, no
proxy. Every change here costs a FreeCAD restart, every change in the
backend a second.
"""
