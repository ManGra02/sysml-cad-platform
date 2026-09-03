"""Verification engine: requirement + mapping + measurement -> verdict.

The one distinction worth holding on to while reading this: mapping validity
and requirement satisfaction are separate questions. This module answers only
the second one. A correctly mapped part that is too long is a violation, not a
bad mapping -- and it is exactly the case the system exists to report.
"""

from __future__ import annotations

import sys

from .adapters import CadAdapter, Unsupported
from .adapters.build123d_adapter import Build123dAdapter
from .adapters.step_adapter import StepAdapter
from .extract import load_with_context
from .mapping import AttributeMapping, Mapping, load_mapping
from .model import (
    DimensionMismatch,
    Requirement,
    Run,
    RunContext,
    Verdict,
    parse_tolerance,
)

#: Adapter registry. A new backend joins this table; nothing else changes.
ADAPTERS: dict[str, type] = {
    "build123d": Build123dAdapter,
    "step": StepAdapter,
}

_STATUS_LABEL = {
    "compliant": "OK",
    "within_tolerance": "TOLERANCE",
    "violated": "VIOLATED",
}


def _leaf(name: str) -> str:
    """Last segment of a qualified name: MotorHousing::motorHousing -> motorHousing."""
    return name.rsplit("::", 1)[-1]


class AdapterPool:
    """One adapter instance per backend, so geometry is built once per run."""

    def __init__(self) -> None:
        self._instances: dict[str, CadAdapter] = {}

    def get(self, name: str) -> CadAdapter:
        if name not in self._instances:
            if name not in ADAPTERS:
                raise Unsupported(f"unknown CAD adapter: {name!r}")
            self._instances[name] = ADAPTERS[name]()
        return self._instances[name]

    @property
    def names(self) -> str:
        return ",".join(sorted(self._instances))

    @property
    def state_id(self) -> str:
        return ",".join(
            f"{name}:{adapter.state_id()}"
            for name, adapter in sorted(self._instances.items())
        )


def _evaluate(
    req: Requirement,
    entry: AttributeMapping,
    mapping: Mapping,
    pool: AdapterPool,
) -> Verdict:
    part = mapping.part_for(entry)
    if part is None:
        raise Unsupported(f"no CAD object mapped for part {entry.sysml_part!r}")
    if not part.usable:
        # FREQ-5 applies to both halves of the mapping: an unconfirmed part
        # entry is not a weaker mapping, it is no mapping at all.
        raise Unsupported(
            f"part {entry.sysml_part!r} is mapped to {part.cad_object!r} with "
            f"status {part.status}, not confirmed -- not used in this run"
        )

    adapter = pool.get(part.adapter)
    measured = adapter.measure(part.cad_object, entry.method, entry.args)
    tolerance = parse_tolerance(entry.tolerance, req.limit)
    status, deviation = req.evaluate(measured, tolerance)

    return Verdict(
        requirement=req,
        measured=measured,
        status=status,
        deviation=deviation,
        method=f"{entry.method}({entry.args or {}}) on {part.adapter}:{part.cad_object}",
        tolerance=tolerance,
    )


def run(source: str | None = None) -> Run:
    requirements, state = load_with_context(source)
    mapping = load_mapping()
    pool = AdapterPool()

    verdicts: list[Verdict] = []
    gaps: list[str] = []

    for req in requirements:
        subject = _leaf(req.subject)
        entry = mapping.for_requirement(req.requirement_id, subject)

        if entry is None:
            gaps.append(f"{req.requirement_id}: no mapping entry for part {subject!r}")
            continue
        if not entry.usable:
            gaps.append(
                f"{req.requirement_id}: mapping is {entry.status}, "
                f"not confirmed -- not used in this run"
            )
            continue

        # The measured attribute comes from the mapping, not from the
        # constraint expression (see the header of extract.py).
        req = Requirement(**{**req.__dict__, "prop": entry.attribute})

        try:
            verdicts.append(_evaluate(req, entry, mapping, pool))
        except Unsupported as exc:
            # FREQ-2: report the gap, never substitute a value.
            gaps.append(f"{req.requirement_id}: {exc}")
        except DimensionMismatch as exc:
            # A mapping entry pointing at the wrong kind of measurement is a
            # bad mapping, and `make gates` is where it gets diagnosed. Here it
            # is simply one requirement that could not be checked -- letting it
            # escape would take every other verdict in the run down with it.
            # The message already names the requirement.
            gaps.append(f"{exc} -- a mapping fault, diagnosed by `make gates`")

    context = RunContext(
        source="api" if source == "api" else "fixture",
        cad_adapter=pool.names,
        cad_state_id=pool.state_id,
        mapping_digest=mapping.digest,
        **state,
    )
    return Run(context=context, verdicts=verdicts, gaps=gaps)


def report(result: Run) -> int:
    ctx = result.context
    print(f"\nsource       : {ctx.source}")
    if ctx.sysml_commit_id:
        print(f"sysml commit : {ctx.sysml_commit_id}")
    print(f"cad state    : {ctx.cad_state_id or '-'}")
    print(f"mapping      : {ctx.mapping_digest}")

    print(f"\n{'ID':<10} {'Attribute':<10} {'Measured':>14} {'Limit':>14} "
          f"{'Deviation':>14}  Status")
    print("-" * 82)
    for v in result.verdicts:
        print(
            f"{v.requirement.requirement_id:<10} {v.requirement.prop:<10} "
            f"{v.measured:>14.4g~P} {v.requirement.limit:>14.4g~P} "
            f"{v.deviation:>+14.4g~P}  {_STATUS_LABEL[v.status]}"
        )
    print("-" * 82)

    counts = {s: 0 for s in _STATUS_LABEL}
    for v in result.verdicts:
        counts[v.status] += 1
    print(
        f"{counts['compliant']} compliant, "
        f"{counts['within_tolerance']} within tolerance, "
        f"{counts['violated']} violated, "
        f"{len(result.gaps)} not checked\n"
    )

    for v in result.verdicts:
        if v.status == "violated":
            print(
                f"  VIOLATED {v.requirement.requirement_id}: "
                f"{v.requirement.prop} = {v.measured:.4g~P} "
                f"{v.requirement.operator} {v.requirement.limit:.4g~P} is false "
                f"(over by {v.deviation:.4g~P}; "
                f"source {v.requirement.element_id}, {v.method})"
            )
        elif v.status == "within_tolerance":
            print(
                f"  TOLERANCE {v.requirement.requirement_id}: "
                f"{v.requirement.prop} = {v.measured:.4g~P} exceeds "
                f"{v.requirement.limit:.4g~P} by {v.deviation:.4g~P}, "
                f"inside the agreed tolerance of {v.tolerance:.4g~P}"
            )

    for gap in result.gaps:
        print(f"  NOT CHECKED {gap}")
    if result.gaps:
        print()

    return result.exit_code


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else None
    return report(run(source))


if __name__ == "__main__":
    raise SystemExit(main())
