"""The proposal store: candidate mappings, before a human has decided on them.

Two stores, two jobs. `mapping/mapping.yaml` is design intent: hand-written,
commented, reviewed, and the only thing a verification run reads.
`mapping/proposals.yaml` is a machine's suggestions: appended to by a proposer,
emptied of nothing, and read by no run at all. Keeping them apart is what makes
FREQ-5 structural rather than a matter of discipline -- a proposer cannot
accidentally influence a verdict, because nothing that reads verdicts ever opens
this file.

A proposal carries what SRS FREQ-4 asks for beyond a plain mapping entry: a
confidence value, a short rationale, and who proposed it. It also carries what
FREQ-5 asks for after the decision: who decided, when, and why if they said no.
Rejections stay in the file. "We looked at this and said no" is worth more than
silence the next time a proposer suggests the same pair.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .mapping import AttributeMapping, Mapping, PartMapping

ROOT = Path(__file__).resolve().parents[2]
PROPOSALS = ROOT / "mapping" / "proposals.yaml"

STATUSES = ("proposed", "confirmed", "rejected")

_HEADER = """\
# Mapping proposals -- MACHINE-WRITTEN. Do not hand-edit; edit mapping.yaml.
#
# Nothing in this file takes part in a verification run. A proposal reaches
# mapping.yaml only through `python -m sysmlcad.confirm <id>`, which re-runs the
# gates first and records who confirmed it and when (SRS FREQ-5).
#
# Rejections are kept rather than deleted: a pair somebody has already turned
# down is worth remembering the next time a proposer suggests it.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Proposal:
    """One candidate mapping, with its provenance."""

    id: str
    sysml_part: str
    attribute: str
    adapter: str
    cad_object: str
    method: str
    args: dict = field(default_factory=dict)
    requirement: str = ""
    direction: str = "cad_owns"

    #: FREQ-4: every candidate carries a confidence value and a short rationale.
    confidence: float = 0.0
    rationale: str = ""
    #: Who suggested it -- "baseline:difflib", "ai:claude-opus-5". Recorded so a
    #: later hit-rate comparison can tell the proposers apart, and so a bad run
    #: can be traced to the thing that produced it (NFREQ-1).
    proposed_by: str = ""
    proposed_at: str = field(default_factory=_now)
    #: What produced it, in enough detail to reproduce the attempt: model id,
    #: prompt digest, response id. Empty for a proposer that has no such thing.
    #: NFREQ-1 -- a suggestion nobody can trace back to its source is not
    #: evidence of anything, and "the AI proposed it" is not a source.
    provenance: dict = field(default_factory=dict)

    status: str = "proposed"
    decided_by: str = ""
    decided_at: str = ""
    reason: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        """What makes two proposals the same suggestion."""
        return (self.sysml_part, self.attribute, self.cad_object, self.method)

    @property
    def pending(self) -> bool:
        return self.status == "proposed"

    def as_mapping_entries(self) -> tuple[PartMapping, AttributeMapping]:
        """The two mapping.yaml entries this proposal would become.

        Rendered as `confirmed`, because that is the question a gate is being
        asked before confirmation: would this be sound *if* it were used?
        """
        part = PartMapping(
            sysml_part=self.sysml_part,
            adapter=self.adapter,
            cad_object=self.cad_object,
            status="confirmed",
        )
        attribute = AttributeMapping(
            sysml_part=self.sysml_part,
            attribute=self.attribute,
            method=self.method,
            requirement=self.requirement,
            args=dict(self.args),
            direction=self.direction,
            status="confirmed",
        )
        return part, attribute


def merged_mapping(mapping: Mapping, proposal: Proposal) -> Mapping:
    """`mapping` as it would be with `proposal` applied.

    What the gates are pointed at before a confirmation: the proposal is checked
    in the company it would keep, so a duplicate of an existing confirmed entry
    is caught by the uniqueness gate rather than discovered afterwards.
    """
    part, attribute = proposal.as_mapping_entries()
    parts = dict(mapping.parts)
    parts.setdefault(proposal.sysml_part, part)
    return Mapping(
        parts=parts,
        attributes=[*mapping.attributes, attribute],
        digest=mapping.digest,
    )


# --------------------------------------------------------------------------
# The file
# --------------------------------------------------------------------------

def load_proposals(path: Path | None = None) -> list[Proposal]:
    path = path or PROPOSALS
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Proposal(**item) for item in data.get("proposals") or []]


def save_proposals(proposals: list[Proposal], path: Path | None = None) -> None:
    path = path or PROPOSALS
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        {"version": 1, "proposals": [asdict(p) for p in proposals]},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=88,
    )
    path.write_text(_HEADER + body, encoding="utf-8")


def next_id(existing: list[Proposal]) -> str:
    used = {
        int(p.id.split("-")[-1])
        for p in existing
        if p.id.startswith("p-") and p.id.split("-")[-1].isdigit()
    }
    return f"p-{(max(used) + 1) if used else 1:02d}"


def add(existing: list[Proposal], candidates: list[Proposal]) -> tuple[list[Proposal], int]:
    """Append the candidates nobody has seen yet. Returns the list and how many
    were added.

    A suggestion already in the file is skipped whatever its status: re-proposing
    something a human rejected would make the store a treadmill.
    """
    known = {p.key for p in existing}
    out = list(existing)
    added = 0
    for candidate in candidates:
        if candidate.key in known:
            continue
        out.append(replace(candidate, id=next_id(out)))
        known.add(candidate.key)
        added += 1
    return out, added


def find(proposals: list[Proposal], proposal_id: str) -> Proposal | None:
    return next((p for p in proposals if p.id == proposal_id), None)


def decide(
    proposals: list[Proposal],
    proposal_id: str,
    status: str,
    user: str,
    reason: str = "",
) -> list[Proposal]:
    """Record a human decision. The proposal stays; only its status changes."""
    if status not in STATUSES:
        raise ValueError(f"status {status!r}, expected one of {STATUSES}")
    return [
        replace(p, status=status, decided_by=user, decided_at=_now(), reason=reason)
        if p.id == proposal_id else p
        for p in proposals
    ]
