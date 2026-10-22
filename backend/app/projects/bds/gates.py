"""Is this mapping entry sound? -- a different question from "is the design ok?".

Mapping validity and requirement satisfaction are separate questions. The gates check
the ASSIGNMENT; verify.py checks SATISFACTION. A correctly mapped part that is too long
is a violation, not a bad mapping, and nothing here may report it as one.

1. existence     -- the model has that attribute, and the adapter can measure it
2. dimension     -- a length attribute must not be mapped to a mass measurement
3. uniqueness    -- no two confirmed entries claim the same attribute or requirement
4. plausibility  -- measured and limit within an order of magnitude of each other

``unknown`` is a real third answer. Plausibility never returns ``invalid``: a part a
hundred times too long may be a wrong mapping or a spectacular violation, and deciding
which is a human's job.

The gates run against UNCONFIRMED entries too -- checking a proposal before a human
confirms it is the point -- so they measure through the adapter directly.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace

from app.projects.bds.adapters import Unsupported
from app.projects.bds.model import BadTolerance, parse_tolerance
from app.projects.bds.proposals import merged_mapping
from app.projects.bds.units import as_json

#: A factor of ten either way catches mm/m and g/kg confusions. Not a tolerance.
PLAUSIBLE_RANGE = (0.1, 10.0)

VERDICTS = ("valid", "unknown", "invalid")

#: A proposal naming a different CAD object for a part that is already mapped.
PART_CONFLICT = "part_conflict"


@dataclass(frozen=True)
class GateResult:
    gate: str
    verdict: str
    detail: str = ""
    code: str = ""

    def to_dict(self):
        out = {"gate": self.gate, "verdict": self.verdict, "detail": self.detail}
        if self.code:
            out["code"] = self.code
        return out


@dataclass(frozen=True)
class MappingCheck:
    sysml_part: str
    attribute: str
    cad_object: str
    method: str
    status: str
    results: tuple = ()
    measured: object = None

    @property
    def verdict(self):
        """The worst answer any gate gave. Nothing averages out."""
        return max((r.verdict for r in self.results), key=VERDICTS.index, default="unknown")

    @property
    def problems(self):
        return tuple(r for r in self.results if r.verdict != "valid")

    def to_dict(self):
        return {"sysml_part": self.sysml_part, "attribute": self.attribute,
                "cad_object": self.cad_object, "method": self.method, "status": self.status,
                "verdict": self.verdict, "measured": as_json(self.measured),
                "gates": [r.to_dict() for r in self.results]}


def gate_existence(entry, catalog, mapping, pool):
    """Both sides have to be there. Returns the measurement too, so no gate measures twice."""
    part = mapping.part_for(entry)
    if part is None:
        return GateResult("existence", "invalid", "no parts: entry for %r" % entry.sysml_part), None

    known_part = catalog.part(entry.sysml_part)
    if known_part is None:
        return GateResult("existence", "invalid", "the model has no part usage %r (known: %s)"
                          % (entry.sysml_part, ", ".join(p.name for p in catalog.parts) or "none")), None

    if catalog.attribute(entry.sysml_part, entry.attribute) is None:
        return GateResult("existence", "invalid", "%s has no attribute %r (has: %s)"
                          % (known_part.definition or entry.sysml_part, entry.attribute,
                             ", ".join(a.name for a in known_part.attributes) or "none")), None
    try:
        measured = pool.get(part.adapter).measure(part.cad_object, entry.method, entry.args)
    except Unsupported as exc:
        return GateResult("existence", "invalid", str(exc)), None
    return GateResult("existence", "valid", format(measured, ".4g~P")), measured


def gate_dimension(entry, catalog, requirement, measured):
    """The measurement must have the dimension the model asks for -- per the attribute's
    SysML type and, when a requirement is linked, the unit of its limit. The tolerance is
    a quantity against the same limit, so it is checked here too."""
    if requirement is not None and entry.tolerance is not None:
        try:
            parse_tolerance(entry.tolerance, requirement.limit)
        except BadTolerance as exc:
            return GateResult("dimension", "invalid", str(exc))

    if measured is None:
        return GateResult("dimension", "unknown", "nothing measured")

    attribute = catalog.attribute(entry.sysml_part, entry.attribute)
    expected = attribute.dimensionality if attribute else None
    if expected is not None and measured.dimensionality != expected:
        return GateResult("dimension", "invalid", "%s yields %s, but %s : %s is %s"
                          % (entry.method, measured.dimensionality, entry.attribute,
                             attribute.type_name, expected))
    if requirement is not None and measured.dimensionality != requirement.limit.dimensionality:
        return GateResult("dimension", "invalid", "%s yields %s, but the limit of %s is %s"
                          % (entry.method, measured.dimensionality, requirement.requirement_id,
                             requirement.limit.dimensionality))
    if expected is None:
        return GateResult("dimension", "unknown", "no dimension known for type %s%s"
                          % ((attribute.type_name if attribute else "?") or "unnamed",
                             "; matches the requirement's limit" if requirement else ""))
    return GateResult("dimension", "valid", str(expected))


def gate_uniqueness(entry, mapping):
    """Nothing may win a tie silently -- ``for_requirement`` returns the first match, so
    a second entry for the same requirement on the same part would never be used."""
    confirmed = [e for e in mapping.attributes if e.usable]

    by_attribute = Counter((e.sysml_part, e.attribute) for e in confirmed)
    if by_attribute[(entry.sysml_part, entry.attribute)] > 1:
        return GateResult("uniqueness", "invalid", "%d confirmed entries for %s.%s"
                          % (by_attribute[(entry.sysml_part, entry.attribute)],
                             entry.sysml_part, entry.attribute))
    if entry.requirement:
        by_requirement = Counter((e.requirement, e.sysml_part) for e in confirmed if e.requirement)
        count = by_requirement[(entry.requirement, entry.sysml_part)]
        if count > 1:
            return GateResult("uniqueness", "invalid", "%d confirmed entries check %s on %s"
                              % (count, entry.requirement, entry.sysml_part))

    own = mapping.part_for(entry)
    if own is None:
        return GateResult("uniqueness", "unknown", "no parts: entry for %r" % entry.sysml_part)
    shared = [name for name, part in mapping.parts.items()
              if part.cad_object == own.cad_object and name != entry.sysml_part]
    if shared:
        return GateResult("uniqueness", "unknown",
                          "the same CAD object also stands for %s" % ", ".join(sorted(shared)))
    return GateResult("uniqueness", "valid")


def gate_plausibility(requirement, measured):
    """Are measurement and limit in the same league? Never ``invalid``."""
    if measured is None or requirement is None:
        return GateResult("plausibility", "unknown", "no measurement or no limit")
    limit = requirement.limit
    if measured.dimensionality != limit.dimensionality:
        return GateResult("plausibility", "unknown", "dimensions differ, ratio meaningless")
    if not limit.magnitude:
        return GateResult("plausibility", "unknown", "limit is zero")
    ratio = float((measured / limit).to("dimensionless").magnitude)
    low, high = PLAUSIBLE_RANGE
    if low <= abs(ratio) <= high:
        return GateResult("plausibility", "valid", "measured/limit = %.3g" % ratio)
    return GateResult("plausibility", "unknown",
                      "measured/limit = %.3g, outside %s-%s -- wrong object, wrong unit, or a large "
                      "genuine deviation" % (ratio, low, high))


def off_axis(entry, catalog):
    """Does a bbox_size entry measure along the axis the workspace's convention names
    for this attribute? Folded into plausibility (never invalid: a part may lie on its
    side), and what surfaces every entry left behind when ``axes`` changes."""
    if entry.method != "bbox_size":
        return None
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", entry.attribute)
    words = re.sub(r"[_\-.]+", " ", spaced).lower().split()
    expected = catalog.axes.get(words[-1]) if words else None
    actual = str((entry.args or {}).get("axis", "")).upper()
    if expected is None or not actual or actual == expected:
        return None
    return ("%s is measured along %s, but this workspace's axis convention puts %s on %s"
            % (entry.attribute, actual, words[-1], expected))


def check_entry(entry, mapping, catalog, requirements, pool):
    """``requirements``: {(requirement_id, part): Requirement}, see extract.by_key."""
    requirement = requirements.get((entry.requirement, entry.sysml_part))
    existence, measured = gate_existence(entry, catalog, mapping, pool)
    part = mapping.part_for(entry)

    plausibility = gate_plausibility(requirement, measured)
    axis_note = off_axis(entry, catalog)
    if axis_note:
        plausibility = GateResult("plausibility", "unknown",
                                  "%s; %s" % (axis_note, plausibility.detail) if plausibility.detail else axis_note)

    return MappingCheck(
        sysml_part=entry.sysml_part,
        attribute=entry.attribute,
        cad_object="%s:%s" % (part.adapter, part.cad_object) if part else "-",
        method=entry.method,
        status=entry.status,
        measured=measured,
        results=(existence, gate_dimension(entry, catalog, requirement, measured),
                 gate_uniqueness(entry, mapping), plausibility),
    )


def check_proposal(proposal, mapping, catalog, requirements, pool):
    """A proposal, gated in the company it would keep -- and on the CAD object it names.

    A part stands for one CAD object, so a proposal naming a different one for an
    already-mapped part is invalid under ``uniqueness``. If the existing part entry is
    wrong, that is a human's edit to ``parts:``, not something a proposal may slip in.
    """
    merged = merged_mapping(mapping, proposal)
    check = check_entry(merged.attributes[-1], merged, catalog, requirements, pool)

    existing = mapping.parts.get(proposal.sysml_part)
    if existing is None or (existing.adapter, existing.cad_object) == (proposal.adapter, proposal.cad_object):
        return check
    conflict = GateResult(
        "uniqueness", "invalid",
        "%s is already mapped to %s:%s, but this proposal names %s:%s. A part stands for one "
        "CAD object; change its parts: entry by hand if that one is wrong"
        % (proposal.sysml_part, existing.adapter, existing.cad_object, proposal.adapter, proposal.cad_object),
        code=PART_CONFLICT,
    )
    return replace(check, results=tuple(conflict if r.gate == "uniqueness" else r for r in check.results))


def check_mapping(mapping, catalog, requirements, pool):
    """Every attribute entry, disabled ones excluded -- a disabled entry is a decision."""
    return [check_entry(entry, mapping, catalog, requirements, pool)
            for entry in mapping.attributes if entry.status != "disabled"]


def unused_parts(mapping):
    """Part entries no attribute entry uses. Not a fault -- a loose end."""
    used = {e.sysml_part for e in mapping.attributes}
    return sorted(name for name in mapping.parts if name not in used)
