"""What exists on each side, as data: the "structural excerpt of both models".

Three consumers, one source: the gates (existence, dimension), the proposers (the
candidate space is this catalogue, filtered) and GET .../catalog.

A SysML attribute carries its dimension in its TYPE (``length : LengthValue``), not in
a unit field. That is the only thing on the SysML side that can say a length must not
be mapped to a mass, so ``_VALUE_TYPES`` turns it into a unit. An unknown type yields
None, never a guess -- the dimension gate then says it could not check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.projects.bds.extract import find_first, of_type
from app.projects.bds.units import ureg
from app.projects.bds.workspace import DEFAULT_AXES

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


@dataclass(frozen=True)
class CatalogAttribute:
    name: str
    element_id: str
    type_name: str = ""

    @property
    def unit(self):
        return _VALUE_TYPES.get(self.type_name)

    @property
    def dimensionality(self):
        unit = self.unit
        return None if unit is None else ureg.Quantity(1, unit).dimensionality

    def to_dict(self):
        dimension = self.dimensionality
        return {"name": self.name, "element_id": self.element_id, "type": self.type_name,
                "dimension": str(dimension) if dimension is not None else None}


@dataclass(frozen=True)
class CatalogPart:
    """A part usage with the attributes its definition declares. ``container`` is the
    part usage it is nested in -- what tells a proposer that ``housing`` is a component
    and ``gearbox`` the assembly around it."""

    name: str
    element_id: str
    definition: str = ""
    definition_id: str = ""
    package: str = ""
    attributes: tuple = ()
    container: str = ""

    @property
    def qualified(self):
        return "%s::%s" % (self.package, self.name) if self.package else self.name

    def to_dict(self):
        return {"name": self.name, "element_id": self.element_id, "definition": self.definition,
                "package": self.package, "container": self.container or None,
                "attributes": [a.to_dict() for a in self.attributes]}


@dataclass(frozen=True)
class Catalog:
    parts: tuple = ()
    targets: tuple = ()
    source: str = ""
    axes: dict = field(default_factory=lambda: dict(DEFAULT_AXES), hash=False)

    def part(self, name):
        return next((p for p in self.parts if p.name == name), None)

    def target(self, reference):
        return next((t for t in self.targets if t.reference == reference), None)

    def attribute(self, part, attribute):
        found = self.part(part)
        if found is None:
            return None
        return next((a for a in found.attributes if a.name == attribute), None)

    def to_dict(self):
        return {"source": self.source, "axes": dict(self.axes),
                "sysml": [p.to_dict() for p in self.parts],
                "cad": [t.to_dict() for t in self.targets]}


def _attributes_of(definition, by_id):
    """The AttributeUsages a PartDefinition owns, via ownedRelationship ->
    FeatureMembership -> member -- explicitly, so a nested part's attributes are
    never collected."""
    out, seen = [], set()
    for ref in definition.get("ownedRelationship", []):
        relationship = by_id.get(ref.get("@id", ""))
        if relationship is None:
            continue
        # A membership names the member under either key; take both, de-duplicate.
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
                value_type, _path = find_first(member, by_id, of_type("AttributeDefinition"))
                out.append(CatalogAttribute(name=name, element_id=member["@id"],
                                            type_name=(value_type or {}).get("declaredName") or ""))
    return tuple(out)


def _owner_walk(element, by_id, stop_types, limit=12):
    current = element
    for _ in range(limit):
        owner_id = (current.get("owner") or {}).get("@id")
        if not owner_id:
            return None
        current = by_id.get(owner_id) or {}
        if current.get("@type") in stop_types:
            return current
        if not current:
            return None
    return None


def _package_of(element, by_id):
    package = _owner_walk(element, by_id, {"Package"})
    return (package or {}).get("declaredName") or ""


def _container_of(element, by_id):
    """The nearest part usage above this one (stops at the package)."""
    owner = _owner_walk(element, by_id, {"PartUsage", "Package"})
    if not owner or owner.get("@type") != "PartUsage":
        return ""
    return owner.get("declaredName") or owner.get("declaredShortName") or ""


def sysml_catalog(elements):
    """Every non-library PartUsage with its definition and attributes."""
    by_id = {e["@id"]: e for e in elements if "@id" in e}
    out = []
    for element in elements:
        if element.get("@type") != "PartUsage" or element.get("isLibraryElement"):
            continue
        name = element.get("declaredName") or element.get("declaredShortName")
        if not name:
            continue
        definition, _path = find_first(element, by_id, of_type("PartDefinition"))
        out.append(CatalogPart(
            name=name,
            element_id=element["@id"],
            definition=(definition or {}).get("declaredName") or "",
            definition_id=(definition or {}).get("@id", ""),
            package=_package_of(element, by_id),
            container=_container_of(element, by_id),
            attributes=_attributes_of(definition, by_id) if definition else (),
        ))
    return tuple(out)


def build_catalog(elements, adapter, axes=None, source=""):
    """Both sides of one workspace: the SysML model's parts, the adapter's targets."""
    return Catalog(parts=sysml_catalog(elements), targets=tuple(adapter.catalog()),
                   source=source, axes=dict(axes or DEFAULT_AXES))
