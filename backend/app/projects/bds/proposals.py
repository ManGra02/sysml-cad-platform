"""The proposal store: candidate mappings, before a human has decided on them.

``mapping.yaml`` is design intent and the only thing a run reads; ``proposals.yaml``
is a machine's suggestions and read by no run at all. Keeping them apart is what makes
"a proposer cannot influence a verdict" structural rather than a matter of discipline.

Rejections stay in the file: "we looked at this and said no" is worth remembering
the next time a proposer suggests the same pair.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

import yaml

from app.projects.bds.mapping import AttributeMapping, Mapping, PartMapping
from app.projects.bds.model import now

STATUSES = ("proposed", "confirmed", "rejected")

_HEADER = """\
# Mapping proposals -- MACHINE-WRITTEN. Do not hand-edit; edit mapping.yaml.
# Nothing in this file takes part in a verification run. A proposal reaches
# mapping.yaml only through POST .../proposals/{id}/confirm, which re-runs the gates.
"""


@dataclass(frozen=True)
class Proposal:
    id: str
    sysml_part: str
    attribute: str
    adapter: str
    cad_object: str
    method: str
    args: dict = field(default_factory=dict)
    requirement: str = ""
    direction: str = "cad_owns"
    confidence: float = 0.0
    rationale: str = ""
    #: "baseline:difflib", "ai:<model>" -- so a scoreboard can tell proposers apart.
    proposed_by: str = ""
    proposed_at: str = field(default_factory=now)
    #: Model id, prompt digest, response id: enough to trace the attempt.
    provenance: dict = field(default_factory=dict)
    status: str = "proposed"
    decided_at: str = ""
    reason: str = ""

    @property
    def key(self):
        """What makes two proposals the same suggestion."""
        return (self.sysml_part, self.attribute, self.cad_object, self.method)

    @property
    def pending(self):
        return self.status == "proposed"

    def as_mapping_entries(self):
        """The two mapping entries this proposal would become -- as ``confirmed``,
        because that is what a gate is asked: would this be sound if it were used?"""
        part = PartMapping(sysml_part=self.sysml_part, adapter=self.adapter,
                           cad_object=self.cad_object, status="confirmed")
        attribute = AttributeMapping(sysml_part=self.sysml_part, attribute=self.attribute,
                                     method=self.method, requirement=self.requirement,
                                     args=dict(self.args), direction=self.direction,
                                     status="confirmed")
        return part, attribute

    def to_dict(self):
        return asdict(self)


def merged_mapping(mapping, proposal):
    """``mapping`` as it would be with ``proposal`` applied. The part entry is the
    proposal's own, so the gates measure the object the proposal names."""
    part, attribute = proposal.as_mapping_entries()
    parts = dict(mapping.parts)
    parts[proposal.sysml_part] = part
    return Mapping(parts=parts, attributes=[*mapping.attributes, attribute], digest=mapping.digest)


def load_proposals(path):
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Proposal(**item) for item in data.get("proposals") or []]


def save_proposals(proposals, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"version": 1, "proposals": [asdict(p) for p in proposals]},
                          sort_keys=False, allow_unicode=True, default_flow_style=False, width=88)
    path.write_text(_HEADER + body, encoding="utf-8")


def next_id(existing):
    used = {int(p.id.split("-")[-1]) for p in existing
            if p.id.startswith("p-") and p.id.split("-")[-1].isdigit()}
    return "p-%02d" % ((max(used) + 1) if used else 1)


def add(existing, candidates):
    """Append the candidates nobody has seen yet -> (list, added). A suggestion already
    in the file is skipped whatever its status: re-proposing a rejection would make the
    store a treadmill."""
    known = {p.key for p in existing}
    out = list(existing)
    added = []
    for candidate in candidates:
        if candidate.key in known:
            continue
        stored = replace(candidate, id=next_id(out))
        out.append(stored)
        added.append(stored)
        known.add(candidate.key)
    return out, added


def find(proposals, proposal_id):
    return next((p for p in proposals if p.id == proposal_id), None)


def decide(proposals, proposal_id, status, reason=""):
    """Record a decision. The proposal stays; only its status changes."""
    if status not in STATUSES:
        raise ValueError("status %r, expected one of %s" % (status, STATUSES))
    return [replace(p, status=status, decided_at=now(), reason=reason) if p.id == proposal_id else p
            for p in proposals]
