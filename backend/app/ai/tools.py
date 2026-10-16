"""Ready-made agent tools over the platform's services, bound to one ProjectContext.

    tools = sysml_tools(self.ctx) + cad_tools(self.ctx)          # read-only
    tools = sysml_tools(self.ctx, write=True)                    # + attribute values (new commit)
    tools = cad_tools(self.ctx, write=True)                      # + property writes, recompute
    tools += calc_tools() + [progress_tool(self.ctx)]            # exact arithmetic, live progress

Each tool returns compact JSON (the model's context is small and costs time).
Errors are returned as ``{"error": ...}`` instead of raised, so the model can
react to e.g. an unknown project name or a stopped FreeCAD.

Own tools: any async function with type hints and a docstring works --
``StructuredTool.from_function(coroutine=fn)`` or LangChain's ``@tool``.
"""

import ast
import functools
import inspect
import json
import math
import operator
from dataclasses import asdict

from langchain_core.tools import StructuredTool

from app.sysml import units

#: Cut-off for a single tool result (characters)
MAX_RESULT = 20_000
#: Hits of sysml_find before the list is cut
MAX_FIND = 20


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


def sysml_tools(ctx, write=False):
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

    async def sysml_find(project: str, name: str, kind: str | None = None) -> dict:
        """Find SysML elements by name or qualified name (exact first, then case-insensitive).
        kind narrows the search: part, part_def, port, requirement, ... Returns only the hits
        (id, name, kind); use sysml_neighbours for the context of one hit."""
        snap = await sysml.snapshot(project)
        hits = snap.find(name, kind=kind)
        return {"version": snap.version, "hits": [_element(e) for e in hits[:MAX_FIND]],
                "truncated": len(hits) > MAX_FIND}

    async def sysml_history(project: str, limit: int = 10) -> dict:
        """The latest commits of a SysML project, newest first (id, created, description).
        Use two commit ids with sysml_diff to see what changed."""
        commits = sorted(await sysml.commits(project), key=lambda c: c.get("created") or "", reverse=True)
        return {"commits": [{k: c.get(k) for k in ("id", "created", "description")}
                            for c in commits[:max(1, limit)]]}

    async def sysml_diff(project: str, base_commit: str, compare_commit: str) -> dict:
        """What changed between two commits of a SysML project: changed attribute values
        (from -> to) and added, removed and changed elements."""
        d = await sysml.diff(project, base_commit, compare_commit)

        def brief(items):
            return [{"id": e["id"], "name": e["name"], "kind": e.get("kind")} for e in items]

        return {"base": d["base"], "compare": d["compare"], "summary": d["summary"],
                "attributes_changed": [{k: a[k] for k in ("owner", "name", "from", "to")}
                                       for a in d["attributes"]["changed"]],
                "elements_added": brief(d["elements"]["added"]),
                "elements_removed": brief(d["elements"]["removed"]),
                "elements_changed": [{"id": e["id"], "name": e["name"], "fields": sorted(e["changes"])}
                                     for e in d["elements"]["changed"]]}

    tools = [sysml_projects, sysml_parts, sysml_requirements, sysml_attributes, sysml_neighbours,
             sysml_find, sysml_history, sysml_diff]

    if write:
        async def sysml_set_attribute_value(project: str, attribute_id: str, value: float,
                                            unit: str | None = None, description: str | None = None) -> dict:
            """Set the numeric value of an existing SysML attribute (attribute id from sysml_attributes)
            -> a new commit on the default branch. A different unit is converted to the modelled one
            (e.g. 11200 g -> 11.2 kg). Only attributes with a literal value can be set."""
            commit = await sysml.write_attribute_value(project, attribute_id, value, unit=unit,
                                                       description=description)
            return {"commit": commit.get("@id"), "description": commit.get("description")}

        tools.append(sysml_set_attribute_value)

    return [_tool(fn) for fn in tools]


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


# -- Arithmetic --------------------------------------------------------------

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {"min": min, "max": max, "abs": abs, "round": round, "sqrt": math.sqrt, "sum": sum}
#: Largest exponent allowed in ``**`` -- 10**100000 would block the backend
MAX_EXPONENT = 100


def evaluate(expression):
    """Arithmetic only: numbers, + - * / // % **, parentheses and _FUNCTIONS. No names, no eval."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError("exponent larger than %d" % MAX_EXPONENT)
            result = _BINARY[type(node.op)](left, right)
            if isinstance(result, int) and result.bit_length() > 4096:   # (9**100)**100 ...
                raise ValueError("number too large")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS
                and not node.keywords):
            return _FUNCTIONS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("not allowed in an expression: %s" % type(node).__name__)
    if len(expression) > 500:
        raise ValueError("expression too long")
    return ev(ast.parse(expression, mode="eval"))


def calc_tools():
    """Exact arithmetic and unit conversion -- models make mistakes with numbers."""

    async def calculate(expression: str) -> dict:
        """Evaluate an arithmetic expression exactly, e.g. "(2.4 + 3.1) * 4" or "sqrt(2) / 2".
        Allowed: numbers, + - * / // % **, parentheses, min max abs round sqrt sum. No units --
        convert first with convert_units. Use this for every calculation instead of computing yourself."""
        result = evaluate(expression)
        if isinstance(result, float):
            result = float("%.12g" % result)   # drop float noise such as 0.30000000000000004
        return {"expression": expression, "result": result}

    async def convert_units(value: float, from_unit: str, to_unit: str) -> dict:
        """Convert a value between units of the same dimension, e.g. 11200 g -> kg, 700 mm -> m,
        250 W -> kW. Fails for different dimensions (kg -> m)."""
        return {"value": units.convert(value, from_unit, to_unit), "unit": to_unit}

    return [_tool(fn) for fn in (calculate, convert_units)]


# -- Progress ----------------------------------------------------------------


def progress_tool(ctx):
    """Live status for the browser: WebSocket frame ``<module id>.agent.progress``."""

    async def report_progress(message: str) -> dict:
        """Tell the user what you are doing right now, in one short sentence (e.g. "Reading the
        CAD tree of Doc"). Use it at the start of longer tasks and between larger steps."""
        ctx.publish("agent.progress", {"message": message})
        return {"reported": True}

    return _tool(report_progress)
