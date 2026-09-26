"""Verification engine: requirement + mapping + measurement -> verdict.

The one distinction worth holding on to while reading this: mapping validity
and requirement satisfaction are separate questions. This module answers only
the second one. A correctly mapped part that is too long is a violation, not a
bad mapping -- and it is exactly the case the system exists to report.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace

from .adapters import CadAdapter, Unsupported
from .adapters.build123d_adapter import Build123dAdapter
from .adapters.step_adapter import StepAdapter
from .extract import load_with_context
from .mapping import AttributeMapping, Mapping, load_mapping
from .project import Project, UnknownProject, add_project_argument, load_project
from .model import (
    BadTolerance,
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


def run(project: Project, source: str | None = None) -> Run:
    """One project, one mapping, one model. `source="api"` reads the server
    project of the same name; anything else reads the project's capture."""
    requirements, skipped, state = load_with_context(project, source)
    mapping = load_mapping(project.mapping_path)
    pool = AdapterPool()

    verdicts: list[Verdict] = []
    # A requirement the extractor could not read is not checked, and saying so
    # is the difference between "0 not checked" being true and being a claim.
    gaps: list[str] = sorted(skipped)

    # Sorted, so the same model state gives the same report byte for byte --
    # the API returns elements in whatever order it likes, and a citable
    # verdict should not depend on that.
    for req in sorted(requirements, key=lambda r: (r.requirement_id, r.subject)):
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
        req = replace(req, prop=entry.attribute)

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
        except BadTolerance as exc:
            # Same reasoning: an unreadable tolerance is one bad entry.
            gaps.append(f"{req.requirement_id}: {exc} -- a mapping fault, "
                        f"diagnosed by `make gates`")

    context = RunContext(
        source="api" if source == "api" else "fixture",
        project=project.name,
        cad_adapter=pool.names,
        cad_state_id=pool.state_id,
        mapping_digest=mapping.digest,
        **state,
    )
    return Run(context=context, verdicts=verdicts, gaps=gaps)


def _miss(v: Verdict) -> tuple[str, str]:
    """How a measurement misses its limit, in words that fit the operator.

    The deviation is signed (`measured - limit`) so the table reads the same way
    for every operator; a sentence does not have to. "Over by -1 mm" for a
    lower bound would tell a reviewer the opposite of what happened.
    """
    amount = f"{abs(v.deviation):.4g~P}"
    if v.requirement.operator in ("<=", "<"):
        return "exceeds", f"over by {amount}"
    if v.requirement.operator in (">=", ">"):
        return "falls short of", f"under by {amount}"
    return "misses", f"off by {amount}"


def report(result: Run) -> int:
    ctx = result.context
    print(f"\nproject      : {ctx.project}")
    print(f"source       : {ctx.source}")
    if ctx.sysml_commit_id:
        print(f"sysml commit : {ctx.sysml_commit_id}")
    print(f"cad state    : {ctx.cad_state_id or '-'}")
    print(f"mapping      : {ctx.mapping_digest}")

    print(f"\n{'ID':<18} {'Attribute':<12} {'Measured':>14} {'Limit':>14} "
          f"{'Deviation':>14}  Status")
    # One requirement satisfied by two parts gives two rows with one id; the
    # part is what tells them apart, so it is shown exactly then.
    repeated = Counter(v.requirement.requirement_id for v in result.verdicts)

    def label(v: Verdict) -> str:
        rid = v.requirement.requirement_id
        return f"{rid}@{v.requirement.subject}" if repeated[rid] > 1 else rid

    print("-" * 92)
    for v in result.verdicts:
        print(
            f"{label(v):<18} {v.requirement.prop:<12} "
            f"{v.measured:>14.4g~P} {v.requirement.limit:>14.4g~P} "
            f"{v.deviation:>+14.4g~P}  {_STATUS_LABEL[v.status]}"
        )
    print("-" * 92)

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
        verb, by = _miss(v)
        if v.status == "violated":
            print(
                f"  VIOLATED {label(v)}: "
                f"{v.requirement.prop} = {v.measured:.4g~P} "
                f"{v.requirement.operator} {v.requirement.limit:.4g~P} is false "
                f"({by}; "
                f"source {v.requirement.element_id}, {v.method})"
            )
        elif v.status == "within_tolerance":
            print(
                f"  TOLERANCE {label(v)}: "
                f"{v.requirement.prop} = {v.measured:.4g~P} {verb} "
                f"{v.requirement.limit:.4g~P} by {abs(v.deviation):.4g~P}, "
                f"inside the agreed tolerance of {v.tolerance:.4g~P}"
            )

    for gap in result.gaps:
        print(f"  NOT CHECKED {gap}")
    if result.gaps:
        print()

    return result.exit_code


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.verify",
        description="Verify one project's requirements against its CAD geometry.",
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
    return report(run(project, args.source))


if __name__ == "__main__":
    raise SystemExit(main())
