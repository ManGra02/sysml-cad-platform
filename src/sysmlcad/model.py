"""Das JSON-Zwischenformat zwischen SysML-Seite und CAD-Seite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .units import Q, ureg

Operator = Literal["<=", ">=", "==", "<", ">"]

_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
}


@dataclass(frozen=True)
class Requirement:
    """Eine SysML-Constraint, normalisiert und einheitenbehaftet."""

    requirement_id: str
    element_id: str
    subject: str
    prop: str
    operator: Operator
    limit: Q
    text: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Requirement":
        return cls(
            requirement_id=d["requirement_id"],
            element_id=d.get("element_id", ""),
            subject=d["subject"],
            prop=d.get("property", ""),
            operator=d["operator"],
            limit=ureg.Quantity(d["value"], d["unit"]),
            text=d.get("text", ""),
        )

    def check(self, measured: Q) -> bool:
        if measured.dimensionality != self.limit.dimensionality:
            raise TypeError(
                f"{self.requirement_id}: Dimension {measured.dimensionality} "
                f"passt nicht zu {self.limit.dimensionality}"
            )
        return _OPS[self.operator](measured, self.limit)


@dataclass(frozen=True)
class Verdict:
    requirement: Requirement
    measured: Q
    passed: bool
    method: str
