"""The mapping: which CAD object is which SysML part, which measurement stands for
which attribute. Schema version 2, one ``mapping.yaml`` per workspace.

The deterministic core: once an entry is confirmed it is an ordinary rule, and
whether a human or an AI proposed it no longer influences the result. Only
confirmed entries take part in a run.

``direction`` is the authority rule, not a merge algorithm: SysML owns limits,
CAD owns actual values, so the two sides cannot collide.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

import yaml

DIRECTIONS = {"sysml_owns", "cad_owns", "both"}
STATUSES = {"proposed", "confirmed", "disabled"}

EMPTY = """\
# Mapping, schema v2 -- see the BDS section of the README.
# Entries arrive through POST .../proposals/{id}/confirm; editing by hand is fine.
version: 2

parts:

attributes:
"""


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
    def usable(self):
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
    def usable(self):
        return self.status == "confirmed"


@dataclass(frozen=True)
class Mapping:
    parts: dict
    attributes: list
    digest: str

    def for_requirement(self, requirement_id, subject=""):
        """The attribute entry a requirement is checked through.

        Matched on the requirement id and, when known, the subject part -- so two parts
        constrained by requirements of the same name cannot be confused. A confirmed
        entry wins over an unconfirmed one for the same pair; an unconfirmed one is
        still returned when it is the only one, so the run can say why it was skipped.
        """
        matches = [e for e in self.attributes
                   if e.requirement == requirement_id and (not subject or e.sysml_part == subject)]
        return next((e for e in matches if e.usable), matches[0] if matches else None)

    def part_for(self, entry):
        return self.parts.get(entry.sysml_part)

    def to_dict(self):
        return {"digest": self.digest,
                "parts": [asdict(p) for p in self.parts.values()],
                "attributes": [asdict(a) for a in self.attributes]}


def empty_mapping():
    return Mapping(parts={}, attributes=[], digest="empty")


def parse_mapping(raw, where="mapping.yaml"):
    data = yaml.safe_load(raw) or {}
    version = data.get("version")
    if version != 2:
        raise ValueError("%s: mapping schema version %r, expected 2" % (where, version))

    parts = {}
    for item in data.get("parts") or []:
        part = PartMapping(**item)
        if part.sysml_part in parts:
            raise ValueError("%s: duplicate part mapping for %r" % (where, part.sysml_part))
        if part.status not in STATUSES:
            raise ValueError("%s: part %r has status %r, expected one of %s"
                             % (where, part.sysml_part, part.status, sorted(STATUSES)))
        parts[part.sysml_part] = part

    attributes = [AttributeMapping(**item) for item in data.get("attributes") or []]
    for entry in attributes:
        label = "%s.%s" % (entry.sysml_part, entry.attribute)
        if entry.direction not in DIRECTIONS:
            raise ValueError("%s: %s has direction %r, expected one of %s"
                             % (where, label, entry.direction, sorted(DIRECTIONS)))
        if entry.status not in STATUSES:
            raise ValueError("%s: %s has status %r, expected one of %s"
                             % (where, label, entry.status, sorted(STATUSES)))
        if entry.sysml_part not in parts:
            raise ValueError("%s: %s refers to part %r, which has no entry under `parts:`"
                             % (where, label, entry.sysml_part))

    return Mapping(parts=parts, attributes=attributes,
                   digest=hashlib.sha256(raw.encode()).hexdigest()[:16])


def load_mapping(path):
    if not path.is_file():
        return empty_mapping()
    return parse_mapping(path.read_text(encoding="utf-8"), path.name)
