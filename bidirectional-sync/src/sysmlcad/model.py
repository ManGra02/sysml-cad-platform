"""The intermediate format between the SysML side and the CAD side.

Three ideas live here:

* `Requirement` -- one SysML constraint, normalised and carrying units.
* `Verdict`     -- the result of evaluating one requirement against one
                   measurement. Three-valued, per SRS FREQ-7: a design can be
                   compliant, inside an agreed tolerance, or violated. A bool
                   cannot express the middle case, and the middle case is the
                   one engineers argue about.
* `RunContext`  -- which model states a verdict came from. SRS FREQ-1 requires
                   that every result be attributable to an exact commit; a
                   verdict without provenance is not evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pint

from .units import Q, ureg

Operator = Literal["<=", ">=", "==", "<", ">"]


class DimensionMismatch(TypeError):
    """The measurement is not the kind of quantity the requirement is about.

    Raised rather than coerced: comparing a length against a mass limit has no
    right answer, and picking one would be the worst kind of wrong. A TypeError
    subclass, so callers that simply refuse bad types still catch it, while
    `verify.run()` can single it out and record a gap instead of losing every
    other verdict in the run to one bad mapping entry.
    """


class BadTolerance(ValueError):
    """A mapping entry's tolerance cannot be read against its requirement's limit.

    `"5 kg"` on a length limit, `"abc%"`, a unit pint does not know. Like
    `DimensionMismatch` this is a mapping fault: `make gates` reports it, and a
    run records it as a gap for that one requirement instead of crashing.
    """


#: `compliant` and `within_tolerance` both leave the pipeline green; only
#: `violated` turns it red. Reporting keeps them apart because "we used up the
#: tolerance" is information, not noise.
Status = Literal["compliant", "within_tolerance", "violated"]

_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
}


def parse_tolerance(spec: str | float | None, limit: Q) -> Q | None:
    """Read a tolerance from the mapping entry.

    Accepts an absolute value with units (``"0.5 mm"``), a bare number in the
    units of the limit (``0.5``), or a percentage of the limit (``"2%"``).
    Returns None when no tolerance is agreed -- which is not the same as a
    tolerance of zero, and is why this is not simply `0`.

    Raises `BadTolerance` for anything it cannot read against `limit`, rather
    than whatever pint or `float()` happened to raise -- so a caller can treat
    it as the mapping fault it is.
    """
    if spec is None:
        return None
    try:
        if isinstance(spec, str):
            text = spec.strip()
            if text.endswith("%"):
                return abs(limit) * (float(text[:-1]) / 100.0)
            return ureg.Quantity(text).to(limit.units)
        return ureg.Quantity(float(spec), limit.units)
    except (ValueError, TypeError, AttributeError, pint.PintError) as exc:
        raise BadTolerance(
            f"tolerance {spec!r} cannot be read against a limit in "
            f"{limit.units:~P}: {exc}"
        ) from exc


@dataclass(frozen=True)
class Requirement:
    """A SysML constraint, normalised and carrying units.

    `subject` is the part the requirement is actually about, resolved through
    the model's own `satisfy` link -- not the subject *parameter* of the
    requirement definition. See `extract.resolve_satisfies`.
    """

    requirement_id: str
    element_id: str
    subject: str
    prop: str
    operator: Operator
    limit: Q
    text: str = ""
    subject_id: str = ""

    def evaluate(self, measured: Q, tolerance: Q | None = None) -> tuple[Status, Q]:
        """Compare a measurement against the limit. Returns status and deviation.

        The deviation is always `measured - limit`, so its sign reads the same
        way for every operator: positive means "over the number in the model".
        """
        if measured.dimensionality != self.limit.dimensionality:
            raise DimensionMismatch(
                f"{self.requirement_id}: dimension {measured.dimensionality} "
                f"does not match {self.limit.dimensionality}"
            )

        deviation = (measured - self.limit).to(self.limit.units)

        if _OPS[self.operator](measured, self.limit):
            return "compliant", deviation

        if tolerance is not None:
            tol = abs(tolerance)
            if self.operator == "==":
                within = abs(deviation) <= tol
            else:
                within = _OPS[self.operator](measured, self._relaxed(tol))
            if within:
                return "within_tolerance", deviation

        return "violated", deviation

    def _relaxed(self, tol: Q) -> Q:
        """The limit loosened by the tolerance, in the direction that helps."""
        if self.operator in ("<=", "<"):
            return self.limit + tol
        if self.operator in (">=", ">"):
            return self.limit - tol
        return self.limit


@dataclass(frozen=True)
class Verdict:
    requirement: Requirement
    measured: Q
    status: Status
    deviation: Q
    method: str
    tolerance: Q | None = None

    @property
    def passed(self) -> bool:
        """Only an outright violation fails the run."""
        return self.status != "violated"


@dataclass(frozen=True)
class RunContext:
    """Which model states produced a set of verdicts.

    SRS FREQ-1: the commit id is recorded "so that every later result can be
    attributed to an exact state of the system model". `cad_state_id` is the
    same idea for the other side -- see `CadAdapter.state_id`.
    """

    source: str
    project: str = ""
    sysml_project_id: str = ""
    sysml_commit_id: str = ""
    cad_adapter: str = ""
    cad_state_id: str = ""
    mapping_digest: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


@dataclass(frozen=True)
class Run:
    """One verification run: what was checked, against which model states.

    `gaps` are requirements that could not be evaluated at all -- no confirmed
    mapping, or a quantity the CAD adapter cannot supply. They are carried
    rather than printed and forgotten, because "we did not check this" and "we
    checked this and it passed" are different claims, and an evidence report
    that conflates them is worthless (SRS SCN-1 lists unmapped elements as open
    items; FREQ-2 requires gaps be reported, not substituted).
    """

    context: RunContext
    verdicts: list[Verdict]
    gaps: list[str] = field(default_factory=list)

    @property
    def violations(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.status == "violated"]

    @property
    def exit_code(self) -> int:
        """Violations fail the run. Gaps do not -- they are reported, not enforced."""
        return 1 if self.violations else 0
