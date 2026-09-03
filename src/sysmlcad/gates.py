"""Is this mapping entry sound? -- a different question from "is the design ok?"

The distinction this module exists to keep is the one the project is easiest to
get wrong: **mapping validity and requirement satisfaction are separate
questions.** The gates check the *assignment* -- does this attribute exist, can
this object be measured that way, is the dimension right, is the number in a
sane range. `verify.py` checks *satisfaction*. A correctly mapped part that is
too long is a violation, not a bad mapping, and nothing here may report it as
one.

The four gates (SRS stage E):

1. dimension     -- a length attribute must not be mapped to a mass measurement
2. existence     -- the model has that attribute, and the adapter can measure it
3. uniqueness    -- no two confirmed entries claim the same attribute or
                    requirement, so nothing silently wins a tie
4. plausibility  -- measured and limit within an order of magnitude of each other

WHAT A GATE MAY CONCLUDE
------------------------
`valid` and `invalid` are claims. `unknown` is the third answer, and it carries
real weight: an attribute whose SysML type this project does not know, or a
ratio that merely looks odd, is not a proven fault. Plausibility in particular
never returns `invalid` -- a part a hundred times too long may be a wrong
mapping or a spectacular violation, and deciding which is a human's job. A gate
that guessed here would be doing exactly what `verify.py` is forbidden to do.

The gates deliberately run against *unconfirmed* entries too. Checking a
proposal before a human confirms it is the entire point (FREQ-5), so this module
measures through the adapter directly rather than through `verify._evaluate`,
which refuses anything not yet confirmed.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass

from .adapters import Unsupported
from .catalog import Catalog, load_catalog
from .extract import load as load_requirements
from .mapping import AttributeMapping, Mapping, load_mapping
from .model import Requirement
from .units import Q
from .verify import AdapterPool, _leaf

#: How far measured and limit may differ before the mapping looks suspicious.
#: A factor of ten either way catches mm/m and g/kg confusions, which is what
#: this gate is for; it is not a tolerance and it never decides a verdict.
PLAUSIBLE_RANGE = (0.1, 10.0)

VERDICTS = ("valid", "unknown", "invalid")


@dataclass(frozen=True)
class GateResult:
    gate: str
    verdict: str
    detail: str = ""


@dataclass(frozen=True)
class MappingCheck:
    """Every gate's answer for one attribute mapping entry."""

    sysml_part: str
    attribute: str
    cad_object: str
    method: str
    status: str
    results: tuple[GateResult, ...] = ()
    measured: Q | None = None

    @property
    def verdict(self) -> str:
        """The worst answer any gate gave. One invalid gate invalidates the
        entry; nothing averages out."""
        return max((r.verdict for r in self.results), key=VERDICTS.index, default="unknown")

    @property
    def problems(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if r.verdict != "valid")


# --------------------------------------------------------------------------
# The individual gates
# --------------------------------------------------------------------------

def gate_existence(
    entry: AttributeMapping,
    catalog: Catalog,
    mapping: Mapping,
    pool: AdapterPool,
) -> tuple[GateResult, Q | None]:
    """Both sides have to be there: the attribute in the model, the measurement
    on the object. Returns the measurement too, so no gate measures twice."""
    part = mapping.part_for(entry)
    if part is None:
        return GateResult("existence", "invalid",
                          f"no parts: entry for {entry.sysml_part!r}"), None

    known_part = catalog.part(entry.sysml_part)
    if known_part is None:
        return GateResult(
            "existence", "invalid",
            f"the model has no part usage {entry.sysml_part!r} "
            f"(known: {', '.join(p.name for p in catalog.parts) or 'none'})",
        ), None

    if catalog.attribute(entry.sysml_part, entry.attribute) is None:
        return GateResult(
            "existence", "invalid",
            f"{known_part.definition or entry.sysml_part} has no attribute "
            f"{entry.attribute!r} "
            f"(has: {', '.join(a.name for a in known_part.attributes) or 'none'})",
        ), None

    try:
        measured = pool.get(part.adapter).measure(part.cad_object, entry.method, entry.args)
    except Unsupported as exc:
        return GateResult("existence", "invalid", str(exc)), None

    return GateResult("existence", "valid", f"{measured:.4g~P}"), measured


def gate_dimension(
    entry: AttributeMapping,
    catalog: Catalog,
    requirement: Requirement | None,
    measured: Q | None,
) -> GateResult:
    """The measurement must have the dimension the model asks for.

    Two sources say what that is, and both are checked: the attribute's SysML
    type (`length : LengthValue`) and, when a requirement is linked, the unit of
    its limit. They should agree; when the model is odd enough that they do not,
    the mismatch is worth seeing.
    """
    if measured is None:
        return GateResult("dimension", "unknown", "nothing measured")

    attribute = catalog.attribute(entry.sysml_part, entry.attribute)
    expected = attribute.dimensionality if attribute else None

    if expected is not None and measured.dimensionality != expected:
        return GateResult(
            "dimension", "invalid",
            f"{entry.method} yields {measured.dimensionality}, but "
            f"{entry.attribute} : {attribute.type_name} is {expected}",
        )

    if requirement is not None:
        limit_dimension = requirement.limit.dimensionality
        if measured.dimensionality != limit_dimension:
            return GateResult(
                "dimension", "invalid",
                f"{entry.method} yields {measured.dimensionality}, but the limit "
                f"of {requirement.requirement_id} is {limit_dimension}",
            )

    if expected is None:
        return GateResult(
            "dimension", "unknown",
            f"no dimension known for type "
            f"{(attribute.type_name if attribute else '?') or 'unnamed'}"
            + ("; matches the requirement's limit" if requirement else ""),
        )

    return GateResult("dimension", "valid", str(expected))


def gate_uniqueness(entry: AttributeMapping, mapping: Mapping) -> GateResult:
    """Nothing may win a tie silently.

    `Mapping.for_requirement` returns the first match, so a second entry for the
    same requirement would simply never be used -- and never be noticed either.
    """
    confirmed = [e for e in mapping.attributes if e.usable]

    by_attribute = Counter((e.sysml_part, e.attribute) for e in confirmed)
    if by_attribute[(entry.sysml_part, entry.attribute)] > 1:
        return GateResult(
            "uniqueness", "invalid",
            f"{by_attribute[(entry.sysml_part, entry.attribute)]} confirmed "
            f"entries for {entry.sysml_part}.{entry.attribute}",
        )

    if entry.requirement:
        by_requirement = Counter(e.requirement for e in confirmed if e.requirement)
        if by_requirement[entry.requirement] > 1:
            return GateResult(
                "uniqueness", "invalid",
                f"{by_requirement[entry.requirement]} confirmed entries check "
                f"{entry.requirement}",
            )

    shared = [
        name for name, part in mapping.parts.items()
        if part.cad_object == (mapping.part_for(entry) or part).cad_object
        and name != entry.sysml_part
    ]
    if shared:
        return GateResult(
            "uniqueness", "unknown",
            f"the same CAD object also stands for {', '.join(sorted(shared))}",
        )

    return GateResult("uniqueness", "valid")


def gate_plausibility(requirement: Requirement | None, measured: Q | None) -> GateResult:
    """Are measurement and limit in the same league?

    Never `invalid`: a part ten times over its limit may be a wrong mapping or a
    real, large violation, and only a human can tell those apart. Saying
    "invalid" here would be this module deciding a verdict, which is exactly
    what it must not do.
    """
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
        return GateResult("plausibility", "valid", f"measured/limit = {ratio:.3g}")
    return GateResult(
        "plausibility", "unknown",
        f"measured/limit = {ratio:.3g}, outside {low}-{high} -- wrong object, "
        f"wrong unit, or a large genuine deviation",
    )


# --------------------------------------------------------------------------
# Running them
# --------------------------------------------------------------------------

def check_entry(
    entry: AttributeMapping,
    mapping: Mapping,
    catalog: Catalog,
    requirements: dict[tuple[str, str], Requirement],
    pool: AdapterPool,
) -> MappingCheck:
    requirement = requirements.get((entry.requirement, entry.sysml_part))
    existence, measured = gate_existence(entry, catalog, mapping, pool)
    part = mapping.part_for(entry)

    return MappingCheck(
        sysml_part=entry.sysml_part,
        attribute=entry.attribute,
        cad_object=f"{part.adapter}:{part.cad_object}" if part else "-",
        method=entry.method,
        status=entry.status,
        measured=measured,
        results=(
            existence,
            gate_dimension(entry, catalog, requirement, measured),
            gate_uniqueness(entry, mapping),
            gate_plausibility(requirement, measured),
        ),
    )


def check_mapping(
    mapping: Mapping | None = None,
    catalog: Catalog | None = None,
    requirements: list[Requirement] | None = None,
    pool: AdapterPool | None = None,
) -> list[MappingCheck]:
    """Every attribute entry, disabled ones excluded.

    A disabled entry is a decision, not an oversight -- gating it would report
    problems nobody intends to fix.
    """
    mapping = mapping or load_mapping()
    pool = pool or AdapterPool()
    catalog = catalog or load_catalog(pool=pool)
    requirements = load_requirements() if requirements is None else requirements

    by_key = {
        (r.requirement_id, _leaf(r.subject)): r for r in requirements
    }
    return [
        check_entry(entry, mapping, catalog, by_key, pool)
        for entry in mapping.attributes
        if entry.status != "disabled"
    ]


def unused_parts(mapping: Mapping) -> list[str]:
    """Part entries no attribute entry uses. Not a fault -- a loose end."""
    used = {e.sysml_part for e in mapping.attributes}
    return sorted(name for name in mapping.parts if name not in used)


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

_MARK = {"valid": "ok", "unknown": "?", "invalid": "FAIL"}


def report(checks: list[MappingCheck], mapping: Mapping | None = None) -> int:
    mapping = mapping or load_mapping()
    print(f"\nmapping      : {mapping.digest}")
    print(f"entries      : {len(checks)}")
    print("\nThis checks the MAPPING, not the design. A correctly mapped part")
    print("that is too long passes here and fails `make verify` -- as it should.\n")

    header = (f"{'part.attribute':<28} {'dimension':>10} {'existence':>10} "
              f"{'uniqueness':>11} {'plausibility':>13}  status")
    print(header)
    print("-" * len(header))

    for check in checks:
        marks = {r.gate: _MARK[r.verdict] for r in check.results}
        print(
            f"{check.sysml_part + '.' + check.attribute:<28} "
            f"{marks.get('dimension', '-'):>10} {marks.get('existence', '-'):>10} "
            f"{marks.get('uniqueness', '-'):>11} {marks.get('plausibility', '-'):>13}"
            f"  {check.verdict}"
        )
    print("-" * len(header))

    counts = Counter(c.verdict for c in checks)
    print(f"{counts['valid']} valid, {counts['unknown']} unknown, "
          f"{counts['invalid']} invalid\n")

    for check in checks:
        for problem in check.problems:
            print(f"  {problem.verdict.upper():<8} {check.sysml_part}.{check.attribute} "
                  f"[{problem.gate}] {problem.detail}")

    loose = unused_parts(mapping)
    if loose:
        print(f"\n  no attribute entry uses these parts: {', '.join(loose)}")
    print()

    return 1 if counts["invalid"] else 0


def main() -> int:
    mapping = load_mapping()
    return report(check_mapping(mapping), mapping)


if __name__ == "__main__":
    raise SystemExit(main())
