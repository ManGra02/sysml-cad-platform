"""Ready-made agent tools over the platform's services, bound to one ProjectContext.

    tools = sysml_tools(self.ctx) + cad_tools(self.ctx)          # read-only
    tools = cad_tools(self.ctx, write=True)                      # + property writes, recompute

Each tool returns compact JSON (the model's context is small and costs time).
Errors are returned as ``{"error": ...}`` instead of raised, so the model can
react to e.g. an unknown project name or a stopped FreeCAD.

Own tools: any async function with type hints and a docstring works --
``StructuredTool.from_function(coroutine=fn)`` or LangChain's ``@tool``.
"""

import functools
import inspect
import json
from dataclasses import asdict

from langchain_core.tools import StructuredTool

#: Cut-off for a single tool result (characters)
MAX_RESULT = 20_000


def _tool(fn):
    @functools.wraps(fn)
    async def safe(*args, **kwargs):
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:   # SysmlError, CadError, ... -> the model sees what went wrong
            result = {"error": {"code": getattr(exc, "code", type(exc).__name__),
                                "message": getattr(exc, "message", str(exc))}}
        text = json.dumps(result, ensure_ascii=False, default=str)
        return text if len(text) <= MAX_RESULT else text[:MAX_RESULT] + " ...(truncated)"
    return StructuredTool.from_function(coroutine=safe, name=fn.__name__,
                                         description=inspect.cleandoc(fn.__doc__))


def _element(e):
    return {"id": e.id, "name": e.name, "kind": e.kind, "qualifiedName": e.qualified_name,
            "parentId": e.parent_id}


def sysml_tools(ctx):
    sysml = ctx.sysml

    async def sysml_projects() -> list:
        """List the SysML v2 projects in the repository (id, name, description)."""
        return [{k: p[k] for k in ("id", "name", "description")} for p in await sysml.projects()]

    async def sysml_parts(project: str, leaf_only: bool = False) -> dict:
        """Part usages of a SysML project (name or id) at the head of its default branch.
        leaf_only=True returns only physical leaf parts, i.e. parts without sub-parts."""
        snap = await sysml.snapshot(project)
        parts = snap.leaf_parts() if leaf_only else snap.parts()
        return {"version": snap.version, "parts": [_element(p) for p in parts]}

    async def sysml_requirements(project: str) -> dict:
        """Requirements of a SysML project with id and text, and which parts satisfy them."""
        snap = await sysml.snapshot(project)
        return {"version": snap.version,
                "requirements": [{**_element(r), "reqId": r.extra.get("req_id"), "text": r.extra.get("text")}
                                 for r in snap.requirements()],
                "satisfies": [{"part": r.source_id, "requirement": r.target_id}
                              for r in snap.relations if r.kind == "satisfies"]}

    async def sysml_attributes(project: str, element_id: str) -> dict:
        """Attributes (value, unit, SI value) of one SysML element, by element id."""
        snap = await sysml.snapshot(project)
        keep = ("id", "name", "value", "unit", "value_si", "unit_si", "expression")
        return {"version": snap.version,
                "attributes": [{k: asdict(a)[k] for k in keep} for a in snap.attributes_of(element_id)]}

    async def sysml_neighbours(project: str, element: str) -> dict:
        """Context of one SysML element (id or name, e.g. "motor"): its type and attributes,
        parent and child parts, the parts it is connected to and via which interface (with
        their attributes), the requirements it satisfies and those inherited from its parent
        assemblies, and allocations. Use this before judging what a part has to fulfil."""
        snap = await sysml.snapshot(project)
        el = snap.element(element)
        if el is None:
            matches = snap.find(element, kind="part") or snap.find(element)
            if len(matches) > 1:
                return {"error": {"code": "ambiguous_element",
                                  "message": "Several elements are called %r, use an id" % element,
                                  "ids": [m.id for m in matches]}}
            el = matches[0] if matches else None
        if el is None:
            return {"error": {"code": "element_not_found", "message": "No element %r in %s" % (element, project)}}
        return snap.neighbours(el.id)

    return [_tool(fn) for fn in (sysml_projects, sysml_parts, sysml_requirements, sysml_attributes,
                                 sysml_neighbours)]


def cad_tools(ctx, write=False):
    cad = ctx.cad

    async def cad_documents() -> dict:
        """Open FreeCAD documents and the active one."""
        return await cad.documents()

    async def cad_tree(doc: str) -> dict:
        """Object tree of a FreeCAD document (names, types, labels, hierarchy)."""
        return await cad.tree(doc)

    async def cad_object(doc: str, name: str) -> dict:
        """One FreeCAD object with its properties, by internal object name."""
        return await cad.object(doc, name)

    async def cad_cells(doc: str, sheet: str, cell_range: str | None = None) -> dict:
        """Used cells (content, value, alias) of a spreadsheet, optionally a range like A1:C10."""
        return await cad.cells(doc, sheet, cell_range)

    tools = [cad_documents, cad_tree, cad_object, cad_cells]

    if write:
        async def cad_set_properties(doc: str, name: str, changes: dict) -> dict:
            """Set properties of a FreeCAD object, e.g. {"Length": "40 mm"}. One undo step."""
            return await cad.patch(doc, name, changes)

        async def cad_recompute(doc: str) -> dict:
            """Recompute a FreeCAD document after changes."""
            return await cad.recompute(doc)

        tools += [cad_set_properties, cad_recompute]

    return [_tool(fn) for fn in tools]
