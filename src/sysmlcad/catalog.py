"""What exists on each side, as data: the structural excerpt of both models.

SRS FREQ-4 says an AI proposer is handed "a structural excerpt of both models".
This module is that excerpt. Nothing here proposes anything and nothing here
measures anything -- it answers only "what is there", for both sides, in one
shape.

Three consumers, one source:

* `gates.py`      -- the existence and dimension checks need to know what a part
                     has and what an adapter can measure.
* `propose.py`    -- the candidate space is exactly this catalogue's cross
                     product, filtered.
* `explore*.py`   -- the human views of the same data.

WHY THE TYPE NAME MATTERS
-------------------------
A SysML attribute carries its dimension in its *type*, not in a unit field:
`attribute length : LengthValue` types the usage against the library's
`LengthValue`. That is the only thing on the SysML side that can say a length
attribute must not be mapped to a mass measurement, so the catalogue reports it
and `_VALUE_TYPES` turns it into a pint unit. An unknown type name yields
`None`, never a guess -- the gate then reports that it could not check, which is
a different answer from "checked and fine".
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .adapters import CadTarget
from .extract import _of_type, find_first
from .sysml_client import SysMLClient
from .units import ureg
from .verify import AdapterPool

ROOT = Path(__file__).resolve().parents[2]

#: A captured API response, so the catalogue (and its tests) run without a
#: server. Lives in fixtures/ rather than out/ because `make clean` empties out/.
ELEMENTS = ROOT / "fixtures" / "elements.json"

#: Where to look for STEP files worth cataloguing. Project layout, not adapter
#: knowledge -- which is why it lives here and not in the adapter.
STEP_DIRS = (ROOT / "fixtures" / "step",)

#: SysML library value type -> the unit this project measures it in. The unit is
#: a stand-in for the dimension; only the dimensionality is ever compared.
#: Deliberately explicit: a mis-typed entry here would let a wrong mapping pass
#: the dimension gate, so this table is meant to be read, not generated.
_VALUE_TYPES = {
    "LengthValue": ureg.mm,
    "MassValue": ureg.kg,
    "VolumeValue": ureg.mm**3,
    "AreaValue": ureg.mm**2,
    "AngleValue": ureg.degree,
    "TemperatureValue": ureg.kelvin,
    "ForceValue": ureg.newton,
    "PressureValue": ureg.pascal,
    "PowerValue": ureg.watt,
    "TimeValue": ureg.second,
    "DimensionlessValue": ureg.dimensionless,
}


# --------------------------------------------------------------------------
# The data
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CatalogAttribute:
    """One attribute of a part definition, with the dimension its type implies."""

    name: str
    element_id: str
    type_name: str = ""

    @property
    def unit(self):
        """The unit this attribute's type implies, or None if the type is not
        in `_VALUE_TYPES`. None means "cannot check", not "no dimension"."""
        return _VALUE_TYPES.get(self.type_name)

    @property
    def dimensionality(self):
        unit = self.unit
        return None if unit is None else ureg.Quantity(1, unit).dimensionality


@dataclass(frozen=True)
class CatalogPart:
    """A part usage, its definition, and the attributes the definition declares.

    The attributes hang off the *definition* because that is where SysML puts
    them, but they are listed under the usage because that is what a mapping
    entry addresses (`sysml_part: motorHousing`).
    """

    name: str
    element_id: str
    definition: str = ""
    definition_id: str = ""
    attributes: tuple[CatalogAttribute, ...] = ()


@dataclass(frozen=True)
class Catalog:
    parts: tuple[CatalogPart, ...] = ()
    targets: tuple[CadTarget, ...] = ()
    source: str = ""

    def part(self, name: str) -> CatalogPart | None:
        return next((p for p in self.parts if p.name == name), None)

    def target(self, reference: str) -> CadTarget | None:
        return next((t for t in self.targets if t.reference == reference), None)

    def attribute(self, part: str, attribute: str) -> CatalogAttribute | None:
        found = self.part(part)
        if found is None:
            return None
        return next((a for a in found.attributes if a.name == attribute), None)


# --------------------------------------------------------------------------
# The SysML side
# --------------------------------------------------------------------------

def _attributes_of(definition: dict, by_id: dict[str, dict]) -> tuple[CatalogAttribute, ...]:
    """The AttributeUsages a PartDefinition owns, with their type names.

    Walks `ownedRelationship -> FeatureMembership -> memberElement` explicitly
    rather than searching the reachable subgraph. The subgraph would work today
    and would start collecting a nested part's attributes as soon as the model
    grows one -- the same reason `extract.resolve_satisfies` searches its two
    branches separately.
    """
    out: list[CatalogAttribute] = []
    seen: set[str] = set()
    for ref in definition.get("ownedRelationship", []):
        relationship = by_id.get(ref.get("@id", ""))
        if relationship is None:
            continue

        # A membership names the same element under both keys. Which one is
        # populated varies with the element; taking both and de-duplicating is
        # steadier than picking one and being surprised later.
        for key in ("memberElement", "ownedRelatedElement"):
            value = relationship.get(key)
            for item in value if isinstance(value, list) else [value]:
                if not isinstance(item, dict) or "@id" not in item:
                    continue
                member = by_id.get(item["@id"])
                if member is None or member.get("@type") != "AttributeUsage":
                    continue
                name = member.get("declaredName")
                if not name or member["@id"] in seen:
                    continue
                seen.add(member["@id"])
                value_type, _path = find_first(
                    member, by_id, _of_type("AttributeDefinition")
                )
                out.append(CatalogAttribute(
                    name=name,
                    element_id=member["@id"],
                    type_name=(value_type or {}).get("declaredName") or "",
                ))
    return tuple(out)


def sysml_catalog(elements: list[dict]) -> tuple[CatalogPart, ...]:
    """Every non-library PartUsage with its definition and attributes.

    Pure function over the element list -- testable against a captured payload,
    with no network.
    """
    by_id = {e["@id"]: e for e in elements if "@id" in e}
    out: list[CatalogPart] = []

    for element in elements:
        if element.get("@type") != "PartUsage" or element.get("isLibraryElement"):
            continue
        name = element.get("declaredName") or element.get("declaredShortName")
        if not name:
            continue

        definition, _path = find_first(element, by_id, _of_type("PartDefinition"))
        out.append(CatalogPart(
            name=name,
            element_id=element["@id"],
            definition=(definition or {}).get("declaredName") or "",
            definition_id=(definition or {}).get("@id", ""),
            attributes=_attributes_of(definition, by_id) if definition else (),
        ))
    return tuple(out)


def load_elements(source: str | None = None) -> tuple[list[dict], str]:
    """Elements plus a one-word note on where they came from.

    `source="api"` reads the live server; anything else reads the captured
    payload, so every consumer of the catalogue works offline by default.
    """
    if source == "api":
        client = SysMLClient()
        try:
            projects = client.projects()
            if not projects:
                raise RuntimeError("no projects on the API server")
            project_id = sorted(projects, key=lambda p: p.get("created", ""))[-1]["@id"]
            return client.all_elements(project_id, client.head_commit(project_id)), "api"
        finally:
            client.close()

    path = Path(source) if source else ELEMENTS
    if not path.is_file():
        raise FileNotFoundError(
            f"no element capture at {path}. Run `python -m sysmlcad.explore` "
            f"against a live server and copy out/elements.json here."
        )
    return json.loads(path.read_text(encoding="utf-8")), str(path.relative_to(ROOT))


# --------------------------------------------------------------------------
# The CAD side
# --------------------------------------------------------------------------

def cad_catalog(pool: AdapterPool | None = None) -> tuple[CadTarget, ...]:
    """Every CAD target this project can currently address.

    The adapters answer "what is in this module / this file"; deciding *which*
    modules and files to ask about is project layout, so it happens here and
    not behind the seam.
    """
    pool = pool or AdapterPool()
    out: list[CadTarget] = list(pool.get("build123d").catalog())

    files = [
        str(path.relative_to(ROOT))
        for directory in STEP_DIRS if directory.is_dir()
        for path in sorted(directory.glob("*.step"))
    ]
    if files:
        out.extend(pool.get("step").catalog(files))
    return tuple(out)


def load_catalog(source: str | None = None, pool: AdapterPool | None = None) -> Catalog:
    elements, origin = load_elements(source)
    return Catalog(
        parts=sysml_catalog(elements),
        targets=cad_catalog(pool),
        source=origin,
    )


# --------------------------------------------------------------------------
# The human view
# --------------------------------------------------------------------------

def report(catalog: Catalog) -> int:
    print(f"\nsysml source : {catalog.source}")
    print(f"parts        : {len(catalog.parts)}")
    print(f"cad targets  : {len(catalog.targets)}\n")

    header = f"{'part / attribute':<32} {'type':<20} {'dimension':<24} element"
    print(header)
    print("-" * len(header))
    for part in catalog.parts:
        print(f"{part.name:<32} {'(' + part.definition + ')':<20} "
              f"{'':<24} {part.element_id[:8]}")
        for attribute in part.attributes:
            dimension = attribute.dimensionality
            print(f"  {attribute.name:<30} {attribute.type_name:<20} "
                  f"{str(dimension) if dimension else 'unknown type':<24} "
                  f"{attribute.element_id[:8]}")

    header = f"\n{'cad_object':<46} {'kind':<9} {'methods':<40} note"
    print(header)
    print("-" * (len(header) - 1))
    for target in catalog.targets:
        print(f"{target.reference:<46} {target.kind:<9} "
              f"{', '.join(target.methods) or '(none)':<40} {target.note}")
        for name, value in target.parameters.items():
            print(f"    {name:<42} {value:~P}")
    print()
    return 0


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else None
    return report(load_catalog(source))


if __name__ == "__main__":
    raise SystemExit(main())
