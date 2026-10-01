"""Small SysML v2 demo models as commit payloads -- test data without the SysML v2 Pilot.

The generated JSON is a *simplified* but valid-for-Flexo subset of the SysML v2 metamodel
(owners, FeatureValues, literal + unit expressions, requirements, satisfy, interface).
For full-fidelity models, author them in the SysML v2 Pilot (Jupyter) and `%publish` to Flexo,
or export JSON and load it with `uv run python -m app.sysml load-file`.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

_NS = uuid.UUID("6f1c2a1e-6a57-4a4f-9d7e-2b8f0c1d9e01")


class ModelBuilder:
    def __init__(self, seed: str = "demo"):
        self.seed = seed
        self.els: dict[str, dict] = {}
        self._qn: dict[str, str] = {}

    def _id(self, key: str) -> str:
        return str(uuid.uuid5(_NS, f"{self.seed}/{key}"))

    def _add(self, key: str, type_: str, owner: str | None, **props) -> str:
        eid = self._id(key)
        el = {"@type": type_, "@id": eid, "elementId": eid, **props}
        if owner:
            el["owner"] = {"@id": owner}
            el["owningNamespace"] = {"@id": owner}
            if type_.endswith("Usage"):
                el["owningType"] = {"@id": owner}
        name = props.get("declaredName")
        if name:
            parent_qn = self._qn.get(owner or "", "")
            self._qn[eid] = f"{parent_qn}::{name}" if parent_qn else name
            el["qualifiedName"] = self._qn[eid]
            el["name"] = name
        self.els[eid] = el
        return eid

    # ------------------------------------------------------------------ element helpers
    def package(self, name: str, owner: str | None = None) -> str:
        return self._add(f"pkg/{name}", "Package", owner, declaredName=name)

    def unit(self, symbol: str, name: str) -> str:
        # stands in for the ISQ/SI library unit (library elements are normally not stored in the project)
        return self._add(f"unit/{symbol}", "AttributeUsage", None, declaredName=name, declaredShortName=symbol,
                         shortName=symbol, isLibraryElement=True)

    def part_def(self, name: str, owner: str) -> str:
        return self._add(f"def/{name}", "PartDefinition", owner, declaredName=name)

    def part(self, name: str, owner: str, definition: str | None = None, key: str | None = None) -> str:
        extra = {"definition": [{"@id": definition}], "type": [{"@id": definition}]} if definition else {}
        return self._add(f"part/{key or name}", "PartUsage", owner, declaredName=name, **extra)

    def attribute(self, name: str, owner: str, value: float | int | None = None, unit: str | None = None) -> str:
        aid = self._add(f"attr/{owner}/{name}", "AttributeUsage", owner, declaredName=name)
        if value is None:
            return aid
        lit_type = "LiteralInteger" if isinstance(value, int) else "LiteralRational"
        if unit:
            expr = self._add(f"expr/{aid}", "OperatorExpression", aid, operator="[")
            lit = self._add(f"lit/{aid}", lit_type, expr, value=value)
            ref = self._add(f"uref/{aid}", "FeatureReferenceExpression", expr, referent={"@id": self._id(f"unit/{unit}")})
            self.els[expr]["argument"] = [{"@id": lit}, {"@id": ref}]
        else:
            expr = self._add(f"lit/{aid}", lit_type, aid, value=value)
        self._add(f"fv/{aid}", "FeatureValue", aid, featureWithValue={"@id": aid}, value={"@id": expr},
                  memberElement={"@id": expr})
        return aid

    def requirement(self, name: str, owner: str, req_id: str, text: str) -> str:
        rid = self._add(f"req/{name}", "RequirementUsage", owner, declaredName=name, declaredShortName=req_id, reqId=req_id)
        self._add(f"doc/{name}", "Documentation", rid, body=text, annotatedElement=[{"@id": rid}])
        return rid

    def satisfy(self, requirement: str, by: str, owner: str) -> str:
        return self._add(f"sat/{requirement}/{by}", "SatisfyRequirementUsage", owner,
                         satisfiedRequirement={"@id": requirement}, satisfyingFeature={"@id": by})

    def interface(self, name: str, a: str, b: str, owner: str) -> str:
        return self._add(f"if/{name}", "InterfaceUsage", owner, declaredName=name,
                         relatedFeature=[{"@id": a}, {"@id": b}], sourceFeature={"@id": a}, targetFeature=[{"@id": b}])

    # ------------------------------------------------------------------ output
    def changes(self) -> list[dict]:
        return [{"identity": {"@id": eid}, "payload": el} for eid, el in self.els.items()]

    def commit_payload(self, description: str = "") -> dict:
        return {"@type": "Commit", "description": description,
                "change": [{"@type": "DataVersion", **c} for c in self.changes()]}


def build_ebike() -> ModelBuilder:
    """E-bike drive unit - the demo system used in the UI mockups and for the CAD side."""
    m = ModelBuilder("ebike")
    for sym, name in [("kg", "kilogram"), ("mm", "millimetre"), ("W", "watt"), ("V", "volt")]:
        m.unit(sym, name)
    root = m.package("EBikeDemo")
    defs = m.package("Definitions", root)
    d = {n: m.part_def(n, defs) for n in ["EBike", "DriveUnit", "Motor", "Battery", "Controller",
                                          "CoolingSystem", "SensorMount", "Frame", "MountingBracket",
                                          "CableGuide", "Wheelset"]}
    use = m.package("Usages", root)
    bike = m.part("eBike", use, d["EBike"])
    du = m.part("driveUnit", bike, d["DriveUnit"])
    m.attribute("massBudget", du, 18.0, "kg")
    motor = m.part("motor", du, d["Motor"])
    m.attribute("mass", motor, 9.8, "kg")
    m.attribute("maxMass", motor, 10.0, "kg")
    m.attribute("ratedPower", motor, 250, "W")
    bat = m.part("battery", du, d["Battery"])
    m.attribute("mass", bat, 3.2, "kg")
    m.attribute("voltage", bat, 36, "V")
    m.attribute("envelopeLength", bat, 360, "mm")
    ctrl = m.part("controller", du, d["Controller"])
    m.attribute("mass", ctrl, 1.2, "kg")
    cool = m.part("coolingSystem", du, d["CoolingSystem"])
    m.attribute("heatDissipation", cool, 250, "W")
    m.part("sensorMount", du, d["SensorMount"])
    frame = m.part("frame", bike, d["Frame"])
    m.attribute("holeSpacing", frame, 80.0, "mm")
    m.part("mountingBracket", frame, d["MountingBracket"])
    m.part("cableGuide", frame, d["CableGuide"])
    wheels = m.part("wheelset", bike, d["Wheelset"])
    m.attribute("diameter", wheels, 700, "mm")
    m.interface("motorMount", motor, frame, bike)

    reqs = m.package("Requirements", root)
    r1 = m.requirement("MaxMotorMass", reqs, "REQ-MOT-004", "The motor mass shall not exceed 10 kg.")
    r2 = m.requirement("DriveUnitMassBudget", reqs, "REQ-DU-001", "The drive unit mass shall not exceed 18 kg.")
    r3 = m.requirement("MountHoleSpacing", reqs, "REQ-FR-002", "Motor mounting holes shall be spaced 80 mm ± 0.5 mm.")
    m.satisfy(r1, motor, bike)
    m.satisfy(r2, du, bike)
    m.satisfy(r3, frame, bike)
    return m


#: data/examples/sysml/ in the repository root
SAMPLES_DIR = Path(__file__).resolve().parents[3] / "data" / "examples" / "sysml"


def load_sample(name: str = "parts-tree") -> dict:
    """'ebike' (generated) or 'parts-tree' (Flexo test model 'PartsTreeRedefinition.json')."""
    if name == "ebike":
        return build_ebike().commit_payload("E-bike demo model")
    path = SAMPLES_DIR / "PartsTreeRedefinition.json"
    return json.loads(path.read_text(encoding="utf-8"))
