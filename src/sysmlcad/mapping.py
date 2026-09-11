"""Loading and resolving the mapping.

The mapping is the deterministic core of the whole system. SRS FREQ-5 puts it
plainly: once an entry is confirmed it "is an ordinary deterministic rule and
its origin no longer influences the result". Whether a human or an AI proposed
it changes nothing about how it is applied -- which is exactly what makes an AI
proposal step safe to add later.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

#: No default path. A mapping belongs to a project (`Project.mapping_path`);
#: a module-level default was how two models ended up sharing one file.

#: Who owns a value. The authority rule, not a merge algorithm: if SysML owns
#: limits and CAD owns actual values, the two sides cannot collide, and all
#: that is left are violations. Nothing writes yet -- the field exists so that
#: enabling writes later is a change of behaviour, not a schema migration.
DIRECTIONS = {"sysml_owns", "cad_owns", "both"}

STATUSES = {"proposed", "confirmed", "disabled"}


@dataclass(frozen=True)
class PartMapping:
    sysml_part: str
    adapter: str
    cad_object: str
    status: str = "proposed"
    author: str = ""
    confirmed_at: str = ""
    note: str = ""

    @property
    def usable(self) -> bool:
        """Only confirmed entries take part in a run -- same rule as for
        attributes. Which CAD object stands for which part is as much a human
        decision as which measurement stands for which attribute, and an
        AI-written part entry must not be live the moment it is written."""
        return self.status == "confirmed"


@dataclass(frozen=True)
class AttributeMapping:
    sysml_part: str
    attribute: str
    method: str
    requirement: str = ""
    args: dict | None = None
    direction: str = "cad_owns"
    tolerance: str | float | None = None
    status: str = "proposed"
    author: str = ""
    confirmed_at: str = ""
    note: str = ""

    @property
    def usable(self) -> bool:
        """Only confirmed entries take part in a run.

        SRS FREQ-5: no entry is used in any synchronisation or verification run
        before a human has confirmed it. A proposal that silently took effect
        would defeat the point of proposing it.
        """
        return self.status == "confirmed"


@dataclass(frozen=True)
class Mapping:
    parts: dict[str, PartMapping]
    attributes: list[AttributeMapping]
    digest: str

    def for_requirement(self, requirement_id: str, subject: str = "") -> AttributeMapping | None:
        """The attribute entry that a requirement is checked through.

        Matched on the requirement id, and on the subject part too when the
        model told us one -- so that two parts constrained by requirements of
        the same name cannot be confused for each other.
        """
        for entry in self.attributes:
            if entry.requirement != requirement_id:
                continue
            if subject and entry.sysml_part != subject:
                continue
            return entry
        return None

    def part_for(self, entry: AttributeMapping) -> PartMapping | None:
        return self.parts.get(entry.sysml_part)


def load_mapping(path: Path) -> Mapping:
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    version = data.get("version")
    if version != 2:
        raise ValueError(
            f"{path}: mapping schema version {version!r}, expected 2. "
            f"v1 keyed on requirement_id + cad_module; v2 anchors on parts."
        )

    parts: dict[str, PartMapping] = {}
    for item in data.get("parts") or []:
        part = PartMapping(**item)
        if part.sysml_part in parts:
            raise ValueError(f"{path}: duplicate part mapping for {part.sysml_part!r}")
        if part.status not in STATUSES:
            raise ValueError(
                f"{path}: part {part.sysml_part!r} has status {part.status!r}, "
                f"expected one of {sorted(STATUSES)}"
            )
        parts[part.sysml_part] = part

    attributes = [AttributeMapping(**item) for item in data.get("attributes") or []]

    for entry in attributes:
        if entry.direction not in DIRECTIONS:
            raise ValueError(
                f"{path}: {entry.sysml_part}.{entry.attribute} has direction "
                f"{entry.direction!r}, expected one of {sorted(DIRECTIONS)}"
            )
        if entry.status not in STATUSES:
            raise ValueError(
                f"{path}: {entry.sysml_part}.{entry.attribute} has status "
                f"{entry.status!r}, expected one of {sorted(STATUSES)}"
            )
        if entry.sysml_part not in parts:
            raise ValueError(
                f"{path}: {entry.sysml_part}.{entry.attribute} refers to part "
                f"{entry.sysml_part!r}, which has no entry under `parts:`"
            )

    return Mapping(
        parts=parts,
        attributes=attributes,
        digest=hashlib.sha256(raw.encode()).hexdigest()[:16],
    )
