"""Common engineering model: the neutral structures every adapter (SysML, FreeCAD, ...) returns.

Agree these with the CAD adapter team - the rest of the platform only sees these classes.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator


# relationship-like elements that are shown as links (requirements view), not as tree nodes
TREE_HIDDEN_KINDS = {"satisfy"}


@dataclass
class ModelElement:
    id: str                       # SysML: element @id (stable across commits). CAD: doc uuid + obj.Name
    name: str
    kind: str                     # part | part_def | port | interface | connection | requirement | constraint | ...
    source: str = "sysml"         # sysml | cad
    native_type: str = ""         # e.g. "PartUsage", "PartDesign::Body"
    qualified_name: str = ""
    parent_id: str | None = None  # structural parent (part tree)
    type_ids: list[str] = field(default_factory=list)  # definitions this usage is typed by
    short_name: str | None = None
    doc: str | None = None
    is_definition: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Attribute:
    id: str                       # SysML: AttributeUsage @id  (mappings point at THIS, not at the name)
    owner_id: str                 # element the attribute belongs to
    name: str
    value: float | int | bool | str | None = None
    unit: str | None = None       # unit as written in the model, e.g. "kg", "mm"
    value_si: float | None = None # normalised to SI (kg, m, s, N, W, ...), None if not numeric/unknown unit
    unit_si: str | None = None
    expression: str | None = None # human-readable form, e.g. "1750 [kg]"
    value_element_id: str | None = None   # the literal that holds the number (used for write-back)
    source: str = "sysml"
    warnings: list[str] = field(default_factory=list)


@dataclass
class Relation:
    source_id: str
    target_id: str
    kind: str                     # typed_by | satisfies | connects | allocates | redefines | subsets
    id: str | None = None         # id of the relationship element itself, if any
    source: str = "sysml"


@dataclass
class ModelSnapshot:
    source: str                   # "sysml"
    project_id: str
    version: str                  # SysML commit id -> every downstream result must record this
    branch_id: str | None = None
    retrieved_at: str = ""
    elements: list[ModelElement] = field(default_factory=list)
    attributes: list[Attribute] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- queries
    def element(self, element_id: str) -> ModelElement | None:
        return self._index().get(element_id)

    def by_kind(self, *kinds: str) -> list[ModelElement]:
        return [e for e in self.elements if e.kind in kinds]

    def parts(self) -> list[ModelElement]:
        return self.by_kind("part")

    def requirements(self) -> list[ModelElement]:
        return self.by_kind("requirement", "requirement_def")

    def children(self, element_id: str | None) -> list[ModelElement]:
        return [e for e in self.elements if e.parent_id == element_id]

    def attributes_of(self, element_id: str) -> list[Attribute]:
        return [a for a in self.attributes if a.owner_id == element_id]

    def attribute(self, attribute_id: str) -> Attribute | None:
        return next((a for a in self.attributes if a.id == attribute_id), None)

    def find(self, name: str, kind: str | None = None) -> list[ModelElement]:
        """Exact name (or qualified name) first; falls back to case-insensitive match."""
        pool = [e for e in self.elements if kind is None or e.kind == kind]
        exact = [e for e in pool if e.name == name or e.qualified_name == name]
        if exact:
            return exact
        n = name.lower()
        return [e for e in pool if e.name.lower() == n or e.qualified_name.lower().endswith("::" + n)]

    def leaf_parts(self) -> list[ModelElement]:
        """Physical leaf parts = part usages without child parts. Candidates for 'missing CAD' checks."""
        parents = {e.parent_id for e in self.parts()}
        return [p for p in self.parts() if p.id not in parents]

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.elements:
            out[e.kind] = out.get(e.kind, 0) + 1
        out["attributes"] = len(self.attributes)
        out["relations"] = len(self.relations)
        return out

    def _index(self) -> dict[str, ModelElement]:
        if getattr(self, "_idx", None) is None or len(self._idx) != len(self.elements):  # type: ignore[attr-defined]
            object.__setattr__(self, "_idx", {e.id: e for e in self.elements})
        return self._idx  # type: ignore[attr-defined]

    # ---------------------------------------------------------------- output
    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "project_id": self.project_id, "version": self.version,
            "branch_id": self.branch_id, "retrieved_at": self.retrieved_at,
            "stats": self.stats(),
            "elements": [asdict(e) for e in self.elements],
            "attributes": [asdict(a) for a in self.attributes],
            "relations": [asdict(r) for r in self.relations],
            "warnings": self.warnings,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def iter_tree(self, root_kinds: tuple[str, ...] = ("part", "part_def", "package", "requirement", "requirement_def")
                  ) -> Iterator[tuple[int, ModelElement]]:
        ids = {e.id for e in self.elements}
        roots = [e for e in self.elements if (e.parent_id is None or e.parent_id not in ids) and e.kind in root_kinds + ("package",)]

        def walk(el: ModelElement, depth: int, seen: set[str]):
            if el.id in seen:
                return
            seen.add(el.id)
            yield depth, el
            kids = [c for c in self.children(el.id) if c.kind not in TREE_HIDDEN_KINDS]
            for c in sorted(kids, key=lambda x: (x.kind != "part", x.name)):
                yield from walk(c, depth + 1, seen)

        seen: set[str] = set()
        for r in sorted(roots, key=lambda x: x.name):
            yield from walk(r, 0, seen)

    def tree_text(self, with_attributes: bool = True) -> str:
        lines = []
        for depth, el in self.iter_tree():
            lines.append(f"{'  ' * depth}{el.name}  <{el.native_type}>")
            if with_attributes:
                for a in self.attributes_of(el.id):
                    val = a.expression if a.expression is not None else "(no value)"
                    lines.append(f"{'  ' * (depth + 1)}. {a.name} = {val}")
        return "\n".join(lines)
