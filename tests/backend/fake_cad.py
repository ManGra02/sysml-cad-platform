"""In-memory stand-in for ``ctx.cad`` (CadClient) -- FreeCAD documents for the BDS tests.

Answers the reads the BDS adapter makes (tree, objects with and without geometry,
spreadsheet cells) in the bridge's response shapes, and applies ``create`` and
``set_cells`` operations so limit write-back can be checked end to end.

``gearbox()`` mirrors the PoC's gearbox: an App::Part "Gearbox" with two PartDesign
bodies, Housing 90 x 60 x 40 and Cover 90 x 60 x 6, one bore r = 8 through both,
aluminium, and a Params spreadsheet. ``cube()`` is a plain Part::Box 100 x 200 x 300.
"""

import math
import re

from app.projects.base import CadError, Transaction

ALUMINIUM = {"name": "Aluminum", "uuid": "a1", "default": False,
             "density": {"kind": "quantity", "value": 2.7e-06, "unit": "kg/mm^3", "unitType": "Density"}}
DEFAULT_MATERIAL = {"name": "Default", "uuid": "d0", "default": True, "density": None}


def quantity(value, unit="mm", unit_type="Length"):
    return {"kind": "quantity", "value": value, "unit": unit, "unitType": unit_type,
            "text": "%s %s" % (value, unit)}


def prop(name, value, status="encoded"):
    return {"name": name, "status": status, "value": value}


def shape():
    return prop("Shape", None, status="derived")


def box_geometry(x, y, z, volume=None, cylinders=(), material=None, faces=6):
    return {"null": False, "shapeType": "Solid", "volume": x * y * z if volume is None else volume,
            "boundBox": {"lengths": [x + 0.5, y + 0.5, z + 0.5]},     # deliberately not tight
            "tightBoundBox": {"lengths": [x, y, z]},
            "counts": {"faces": faces}, "cylinders": list(cylinders), "material": material}


class FakeDoc:
    def __init__(self, name):
        self.name = name
        self.objects = {}

    def add(self, name, type_id, label=None, children=(), deps=None, properties=(), geometry=None,
            state=(), internal=False, cells=None):
        self.objects[name] = {
            "name": name, "label": label or name, "typeId": type_id, "children": list(children),
            "deps": list(children if deps is None else deps), "properties": list(properties),
            "geometry": geometry, "state": list(state), "internal": internal, "rev": 1,
            "cells": cells,
        }
        return self.objects[name]


def gearbox():
    doc = FakeDoc("Gearbox")
    bore = math.pi * 8 ** 2
    hole = lambda z: {"radius": 8.0, "kind": "hole", "center": [45.0, 30.0, z], "axis": [0.0, 0.0, 1.0]}  # noqa: E731
    fillet = {"radius": 2.0, "kind": "boss", "center": [0.0, 0.0, 0.0], "axis": [1.0, 0.0, 0.0]}
    doc.add("Part", "App::Part", "Gearbox", children=["Body", "Body001"], properties=[],
            geometry=box_geometry(90, 60, 46, volume=90 * 60 * 46 - bore * 46, material=None))
    doc.add("Body", "PartDesign::Body", "Housing", children=["Sketch", "Pad"],
            deps=["Sketch", "Pad", "Origin"], properties=[shape()],
            geometry=box_geometry(90, 60, 40, volume=90 * 60 * 40 - bore * 40,
                                  # a bore split by a seam is two faces, one feature
                                  cylinders=[hole(0.0), hole(20.0), fillet], material=ALUMINIUM, faces=11))
    doc.add("Sketch", "Sketcher::SketchObject", properties=[shape()])
    doc.add("Pad", "PartDesign::Pad", deps=["Sketch"],
            properties=[shape(), prop("Length", quantity(40.0)), prop("Offset", quantity(0.0))])
    doc.add("Body001", "PartDesign::Body", "Cover", children=["Sketch001", "Pad001"],
            deps=["Sketch001", "Pad001"], properties=[shape()],
            geometry=box_geometry(90, 60, 6, volume=90 * 60 * 6 - bore * 6,
                                  cylinders=[hole(40.0)], material=ALUMINIUM, faces=7))
    doc.add("Sketch001", "Sketcher::SketchObject", properties=[shape()])
    doc.add("Pad001", "PartDesign::Pad", deps=["Sketch001"], properties=[shape(), prop("Length", quantity(6.0))])
    doc.add("Origin", "App::Origin", internal=True)
    doc.add("Spreadsheet", "Spreadsheet::Sheet", "Params", cells={
        "A1": {"content": "HousingLength", "value": "HousingLength", "alias": None},
        "B1": {"content": "=90 mm", "value": quantity(90.0), "alias": "HousingLength"},
        "B2": {"content": "6", "value": 6, "alias": "CoverCount"},
    })
    return doc


def cube(name="Cube", material=None):
    doc = FakeDoc(name)
    doc.add("Box", "Part::Box", "Cube",
            properties=[shape(), prop("Length", quantity(100.0)), prop("Width", quantity(200.0)),
                        prop("Height", quantity(300.0))],
            geometry=box_geometry(100, 200, 300, material=material or DEFAULT_MATERIAL))
    return doc


def _parse_cell(content):
    """What FreeCAD makes of a cell: "=100.0 mm" -> quantity, "abc" -> text."""
    text = content[1:] if content.startswith("=") else content
    match = re.fullmatch(r"\s*([-+0-9.eE]+)\s*([A-Za-z^*/0-9]*)\s*", text)
    if not match:
        return content
    value = float(match.group(1))
    return quantity(value, match.group(2)) if match.group(2) else value


class FakeCad:
    def __init__(self, *documents):
        self.documents = {doc.name: doc for doc in documents}
        self.operations_log = []
        self.reads = []

    def _doc(self, doc):
        if doc not in self.documents:
            raise CadError(404, "doc_not_open", "Document %r is not open" % doc)
        return self.documents[doc]

    async def tree(self, doc):
        self.reads.append(("tree", doc))
        document = self._doc(doc)
        nodes = {}
        for name, obj in document.objects.items():
            nodes[name] = {k: obj[k] for k in ("name", "label", "typeId", "internal", "state", "rev",
                                               "children", "deps")}
        claimed = {c for obj in document.objects.values() for c in obj["children"]}
        return {"doc": doc, "roots": sorted(n for n in nodes if n not in claimed), "nodes": nodes}

    async def get(self, path, *, timeout=None, **query):
        self.reads.append(("get", path, query))
        match = re.fullmatch(r"/documents/([^/]+)/objects", path)
        if not match:
            raise CadError(404, "not_found", path)
        document = self._doc(match.group(1))
        names = query.get("names")
        selected = [document.objects[n] for n in names.split(",")] if names else list(document.objects.values())
        out = []
        for obj in selected:
            if obj["internal"]:
                continue
            entry = {"doc": document.name, "name": obj["name"], "label": obj["label"],
                     "typeId": obj["typeId"], "rev": obj["rev"], "state": obj["state"],
                     "properties": [] if query.get("fields") else obj["properties"]}
            if query.get("include") == "geometry":
                entry["geometry"] = obj["geometry"]
            out.append(entry)
        return {"doc": document.name, "objects": out}

    async def cells(self, doc, sheet, cell_range=None):
        self.reads.append(("cells", doc, sheet))
        obj = self._doc(doc).objects[sheet]
        return {"doc": doc, "sheet": sheet, "cells": {k: dict(v) for k, v in obj["cells"].items()},
                "rev": obj["rev"]}

    def transaction(self, doc, name=None, strict=True):
        return Transaction(self, doc, name, strict)

    async def operations(self, doc, ops, name=None, strict=True):
        self.operations_log.append({"doc": doc, "name": name, "ops": ops})
        document = self._doc(doc)
        created = {}

        def resolve(ref):
            return created[ref[1:]] if ref.startswith("$") else ref

        for op in ops:
            if op["op"] == "create":
                new = op.get("name") or op["type"].split("::")[-1]
                document.add(new, op["type"], op.get("label"), cells={})
                created[op["as"]] = new
            elif op["op"] == "set_cells":
                sheet = document.objects[resolve(op["sheet"])]
                for cell, content in (op.get("cells") or {}).items():
                    current = sheet["cells"].setdefault(cell, {"alias": None})
                    current["content"] = str(content)
                    current["value"] = _parse_cell(str(content))
                for cell, alias in (op.get("aliases") or {}).items():
                    sheet["cells"].setdefault(cell, {"content": "", "value": None})["alias"] = alias
                sheet["rev"] += 1
            else:
                raise AssertionError("FakeCad does not do %r" % op["op"])
        return {"status": "done", "atomic": True, "changed": True, "created": created,
                "results": [{"op": op["op"]} for op in ops], "recomputed": 1, "errors": [], "revs": {}}
