"""The intermediate format between the SysML side and the CAD side.

* ``Requirement`` -- one SysML constraint, normalised and carrying units.
* ``Verdict``     -- one requirement evaluated against one measurement. Three-valued:
                     compliant, within the agreed tolerance, or violated. A bool
                     cannot express the middle case, and that is the one engineers
                     argue about.
* ``RunContext``  -- which model states a verdict came from (SysML commit, CAD state,
                     mapping digest). A verdict without provenance is not evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pint

from app.projects.bds.units import Q, as_json, ureg

Operator = Literal["<=", ">=", "==", "<", ">"]
Status = Literal["compliant", "within_tolerance", "violated"]

_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
}


class DimensionMismatch(TypeError):
    """The measurement is not the kind of quantity the requirement is about.

    Raised rather than coerced: a length against a mass limit has no right answer.
    A run records it as a gap for that one requirement.
    """


class BadTolerance(ValueError):
    """A mapping entry's tolerance cannot be read against its requirement's limit."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_tolerance(spec, limit):
    """``"0.5 mm"``, a bare number in the limit's unit, or ``"2%"`` of the limit.

    None means "no tolerance agreed", which is not the same as a tolerance of zero.
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
        raise BadTolerance("tolerance %r cannot be read against a limit in %s: %s"
                           % (spec, format(limit.units, "~P"), exc)) from exc


@dataclass(frozen=True)
class Requirement:
    """A SysML constraint. ``subject`` is the part it is about, resolved through the
    model's own ``satisfy`` link (see extract.resolve_satisfies)."""

    requirement_id: str
    element_id: str
    subject: str
    prop: str
    operator: Operator
    limit: Q
    text: str = ""
    subject_id: str = ""

    def evaluate(self, measured, tolerance=None):
        """-> (status, deviation). The deviation is always ``measured - limit``, so its
        sign reads the same for every operator: positive means "over the model's number"."""
        if measured.dimensionality != self.limit.dimensionality:
            raise DimensionMismatch("%s: dimension %s does not match %s"
                                    % (self.requirement_id, measured.dimensionality,
                                       self.limit.dimensionality))

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

    def _relaxed(self, tol):
        """The limit loosened by the tolerance, in the direction that helps."""
        if self.operator in ("<=", "<"):
            return self.limit + tol
        if self.operator in (">=", ">"):
            return self.limit - tol
        return self.limit

    def to_dict(self):
        return {"requirement": self.requirement_id, "element_id": self.element_id,
                "subject": self.subject, "subject_id": self.subject_id, "attribute": self.prop,
                "operator": self.operator, "limit": as_json(self.limit), "text": self.text}


@dataclass(frozen=True)
class Verdict:
    requirement: Requirement
    measured: Q
    status: Status
    deviation: Q
    method: str
    tolerance: Q | None = None

    @property
    def passed(self):
        """Only an outright violation fails the run."""
        return self.status != "violated"

    def to_dict(self):
        return {**self.requirement.to_dict(), "measured": as_json(self.measured),
                "deviation": as_json(self.deviation), "tolerance": as_json(self.tolerance),
                "method": self.method, "status": self.status}


@dataclass(frozen=True)
class RunContext:
    workspace: str = ""
    sysml_project_id: str = ""
    sysml_commit_id: str = ""
    cad_adapter: str = ""
    cad_state_id: str = ""
    mapping_digest: str = ""
    started_at: str = field(default_factory=now)


@dataclass(frozen=True)
class Run:
    """One verification run. ``gaps`` are requirements that could not be evaluated at
    all -- "we did not check this" and "we checked this and it passed" are different
    claims, so a gap is never a pass."""

    context: RunContext
    verdicts: list
    gaps: list = field(default_factory=list)

    @property
    def violations(self):
        return [v for v in self.verdicts if v.status == "violated"]

    def to_dict(self):
        counts = {s: 0 for s in ("compliant", "within_tolerance", "violated")}
        for verdict in self.verdicts:
            counts[verdict.status] += 1
        return {
            "context": dict(self.context.__dict__),
            "verdicts": [v.to_dict() for v in self.verdicts],
            "gaps": list(self.gaps),
            "summary": {**counts, "not_checked": len(self.gaps)},
            "violated": bool(self.violations),
        }
