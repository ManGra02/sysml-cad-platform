"""A stand-in FreeCAD worker, speaking protocol 1 over `httpx.MockTransport`.

Two jobs. It lets every decision of `FreeCadAdapter` run with no FreeCAD and
no network -- the same way `test_sysml_client.py` stands in for the SysML
server. And it is the protocol in executable form: what it answers is what
`docs/freecad_worker_protocol.md` promises, so a real worker that behaves
differently from this one is the one that is wrong.

It knows nothing about geometry. Every measurement is a canned answer keyed by
(object name, method, args), which is the point: the client's job is to send
the right question and refuse a wrong answer, not to compute anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

LENGTH = [1, 0, 0, 0, 0, 0, 0, 0]
VOLUME = [3, 0, 0, 0, 0, 0, 0, 0]
MASS = [0, 1, 0, 0, 0, 0, 0, 0]
DENSITY = [-3, 1, 0, 0, 0, 0, 0, 0]          # kg/mm^3, FreeCAD's internal
DIMENSIONLESS = [0, 0, 0, 0, 0, 0, 0, 0]


def q(value: float, unit: list[int]) -> dict:
    return {"value": value, "unit": list(unit)}


def mm(value: float) -> dict:
    return q(value, LENGTH)


#: Aluminium as FreeCAD stores it internally: 2.70 g/cm^3 = 2.7e-6 kg/mm^3.
ALUMINIUM = {"name": "Aluminum", "density": q(2.7e-6, DENSITY)}


def _key(name: str, method: str, args: dict) -> str:
    return f"{name}|{method}|{json.dumps(args or {}, sort_keys=True)}"


@dataclass
class FakeDocument:
    objects: list[dict]
    parameters: dict[str, dict] = field(default_factory=dict)
    measures: dict[str, dict] = field(default_factory=dict)
    #: sheet label -> {"managed": bool, "cells": {alias: quantity}}
    sheets: dict[str, dict] = field(default_factory=dict)

    def answer(self, name: str, method: str, args: dict, value: dict) -> "FakeDocument":
        self.measures[_key(name, method, args)] = value
        return self


@dataclass
class FakeWorker:
    documents: dict[str, FakeDocument]
    protocol: int = 1
    requests: list[tuple[str, dict | None]] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.url.path, body))
        route = {
            "/v1/health": self._health,
            "/v1/document": self._document,
            "/v1/measure": self._measure,
            "/v1/write_limits": self._write_limits,
        }.get(request.url.path)
        if route is None:
            return httpx.Response(404, text="no such route")
        return httpx.Response(200, json=route(body))

    # -- routes -------------------------------------------------------------

    def _health(self, _body):
        return {"ok": {"freecad": "1.0.2 (fake)", "protocol": self.protocol}}

    def _doc(self, body) -> FakeDocument | dict:
        document = self.documents.get(body.get("file"))
        if document is None:
            return {"unsupported": f"no FreeCAD document at {body.get('file')}"}
        return document

    def _document(self, body):
        document = self._doc(body)
        if isinstance(document, dict):
            return document
        return {"ok": {"objects": document.objects, "parameters": document.parameters}}

    def _measure(self, body):
        document = self._doc(body)
        if isinstance(document, dict):
            return document
        value = document.measures.get(_key(body["object"], body["method"], body.get("args") or {}))
        if value is None:
            return {"unsupported": f"{body['object']}: cannot measure {body['method']}"}
        return {"ok": value}

    def _write_limits(self, body):
        document = self._doc(body)
        if isinstance(document, dict):
            return document
        sheet = document.sheets.get(body["sheet"])
        if sheet is not None and not sheet["managed"]:
            return {"unsupported": (
                f"sheet {body['sheet']!r} exists and is not managed by sysmlcad -- "
                f"refusing to write into a sheet somebody else owns"
            )}
        cells = dict(sheet["cells"]) if sheet else {}
        changes = []
        for alias, new in sorted(body["values"].items()):
            old = cells.get(alias)
            if old != new:
                changes.append({"alias": alias, "old": old, "new": new})
                cells[alias] = new
        if body["apply"] and changes:
            document.sheets[body["sheet"]] = {"managed": True, "cells": cells}
        return {"ok": {"changes": changes, "saved": bool(body["apply"] and changes)}}


def cube_document() -> FakeDocument:
    """A 100 x 200 x 300 mm box driven by spreadsheet aliases, in aluminium --
    the FreeCAD original of `projects/cube_freecad`."""
    return FakeDocument(
        objects=[
            {"label": "Box", "name": "Box", "type": "Part::Box", "parent": None,
             "has_shape": True, "error": None, "material": ALUMINIUM},
        ],
        parameters={
            "Params.Length": mm(100.0),
            "Params.Width": mm(200.0),
            "Params.Height": mm(300.0),
            "Box.Length": mm(100.0),
            "Params.Count": q(3.0, DIMENSIONLESS),
        },
    ).answer("Box", "bbox_size", {"axis": "X"}, mm(100.0)) \
     .answer("Box", "bbox_size", {"axis": "Y"}, mm(200.0)) \
     .answer("Box", "bbox_size", {"axis": "Z"}, mm(300.0)) \
     .answer("Box", "volume", {}, q(6_000_000.0, VOLUME)) \
     .answer("Box", "face_count", {}, q(6.0, DIMENSIONLESS))
