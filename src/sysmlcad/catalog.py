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

import sys
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import CadTarget
from .extract import _of_type, fetch_elements, find_first
from .project import DEFAULT_AXES, Project, UnknownProject, add_project_argument, load_project
from .units import ureg
from .verify import AdapterPool

ROOT = Path(__file__).resolve().parents[2]

#: One project, one capture, never merged. The catalogue used to glob every
#: capture it could find and merge them, which put two unrelated models' parts
#: side by side -- two `Housing`s from two models, indistinguishable to a
#: proposer. A catalogue describes ONE model; which one is the project's job.

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
    package: str = ""
    attributes: tuple[CatalogAttribute, ...] = ()

    @property
    def qualified(self) -> str:
        """`Gearbox::housing`. Two published models can both have a `housing`,
        and the bare name cannot tell them apart -- which is exactly the mistake
        a proposer makes when the catalogue does not say."""
        return f"{self.package}::{self.name}" if self.package else self.name


@dataclass(frozen=True)
class Catalog:
    parts: tuple[CatalogPart, ...] = ()
    targets: tuple[CadTarget, ...] = ()
    source: str = ""
    #: Which bounding-box axis each named dimension is measured along on this
    #: project's CAD side -- `Project.axes`. Part of the excerpt because it is a
    #: fact about how the CAD side is oriented, and every proposer needs it.
    axes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_AXES), hash=False)

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


def _package_of(element: dict, by_id: dict[str, dict], limit: int = 12) -> str:
    """The package a part lives in, by walking owners upward.

    Upward, deliberately: `owner` is in `extract._UPWARD_FIELDS` and never
    followed during a downward search, because following it would make the whole
    model reachable from any node. Here it is exactly what is wanted, and a
    nested part (`gearbox.housing`) needs several steps to reach the package.
    """
    current = element
    for _ in range(limit):
        owner_id = (current.get("owner") or {}).get("@id")
        if not owner_id:
            return ""
        current = by_id.get(owner_id) or {}
        if current.get("@type") == "Package":
            return current.get("declaredName") or ""
    return ""


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
            package=_package_of(element, by_id),
            attributes=_attributes_of(definition, by_id) if definition else (),
        ))
    return tuple(out)


def load_elements(project: Project, source: str | None = None) -> tuple[list[dict], str]:
    """This project's elements, plus a one-word note on where they came from.

    `source="api"` reads the server project of the same name; anything else
    reads the project's capture, so every consumer works offline by default.
    """
    if source == "api":
        # The same by-name lookup `verify api` uses -- one implementation, so
        # the catalogue and the verifier cannot disagree about which project
        # a name means.
        elements, _state = fetch_elements(project.sysml_project)
        return elements, "api"

    path = project.elements_path
    return project.elements(), str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


# --------------------------------------------------------------------------
# The CAD side
# --------------------------------------------------------------------------

def cad_catalog(
    pool: AdapterPool | None = None,
    project_dirs: tuple[Path, ...] = (),
) -> tuple[CadTarget, ...]:
    """Every CAD target this project can currently address.

    The adapters answer "what is in this module / this file"; deciding *which*
    modules and files to ask about is project layout, so it happens here and
    not behind the seam.

    `project_dirs` adds a project's own STEP files: an export that belongs to
    one model lives in that model's directory, next to its mapping, rather
    than among the shared fixtures every project sees.
    """
    pool = pool or AdapterPool()
    out: list[CadTarget] = list(pool.get("build123d").catalog())

    def reference(path: Path) -> str:
        return str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)

    files = [
        reference(path)
        for directory in (*STEP_DIRS, *project_dirs) if directory.is_dir()
        for path in sorted(directory.glob("*.step"))
    ]
    if files:
        out.extend(pool.get("step").catalog(files))
    return tuple(out)


def load_catalog(
    project: Project,
    source: str | None = None,
    pool: AdapterPool | None = None,
) -> Catalog:
    elements, origin = load_elements(project, source)
    return Catalog(
        parts=sysml_catalog(elements),
        targets=cad_catalog(pool, project_dirs=(project.root,)),
        source=origin,
        axes=dict(project.axes),
    )


# --------------------------------------------------------------------------
# The human view
# --------------------------------------------------------------------------

def report(catalog: Catalog) -> int:
    print(f"\nsysml source : {catalog.source}")
    print(f"parts        : {len(catalog.parts)}")
    print(f"cad targets  : {len(catalog.targets)}")
    print(f"axes         : length {catalog.axes.get('length', '?')}, "
          f"width {catalog.axes.get('width', '?')}, "
          f"height {catalog.axes.get('height', '?')}"
          f"{'' if catalog.axes == DEFAULT_AXES else '  (project.yaml)'}\n")

    header = f"{'part / attribute':<32} {'type':<20} {'dimension':<24} element"
    print(header)
    print("-" * len(header))
    for part in catalog.parts:
        print(f"{part.qualified:<32} {'(' + part.definition + ')':<20} "
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


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.catalog",
        description="What exists on each side of one project, as data.",
    )
    add_project_argument(parser)
    parser.add_argument("source", nargs="?", default=None,
                        help="'api' for the live server; omit for the project's capture")
    args = parser.parse_args(argv)

    try:
        project = load_project(args.project)
    except UnknownProject as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return report(load_catalog(project, args.source))


if __name__ == "__main__":
    raise SystemExit(main())
