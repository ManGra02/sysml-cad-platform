"""Evaluate SysML v2 value expressions from the API JSON.

`mass = 1750 [kg];` is not a plain field. In the API it is:
    AttributeUsage(mass) <-featureWithValue- FeatureValue -value-> OperatorExpression(operator "[")
        argument[0] = LiteralInteger(1750)
        argument[1] = FeatureReferenceExpression(referent -> AttributeUsage "kilogram", shortName "kg")
This module walks such trees and returns (value, unit, text).
"""
from __future__ import annotations

import math
import operator as op
from dataclasses import dataclass, field
from typing import Any

LITERAL_TYPES = {"LiteralInteger", "LiteralRational", "LiteralReal", "LiteralBoolean", "LiteralString", "LiteralInfinity"}
_BINARY = {"+": op.add, "-": op.sub, "*": op.mul, "/": op.truediv, "**": op.pow, "^": op.pow}
_COMPARE = {"<": op.lt, "<=": op.le, ">": op.gt, ">=": op.ge, "==": op.eq, "!=": op.ne}


@dataclass
class EvalResult:
    value: Any = None
    unit: str | None = None
    text: str = ""
    literal_id: str | None = None      # element that stores the number (for write-back)
    warnings: list[str] = field(default_factory=list)


def ref_id(v: Any) -> str | None:
    if isinstance(v, dict):
        return v.get("@id")
    if isinstance(v, str):
        return v
    return None


def ref_ids(v: Any) -> list[str]:
    if isinstance(v, list):
        return [i for i in (ref_id(x) for x in v) if i]
    i = ref_id(v)
    return [i] if i else []


class ExpressionEvaluator:
    def __init__(self, elements: dict[str, dict], unit_names: dict[str, str] | None = None,
                 value_of_feature=None):
        self.els = elements
        self.unit_names = unit_names or {}      # element id -> short name, taken from memberships
        self.value_of_feature = value_of_feature  # callback(feature_id) -> EvalResult | None
        self._owned_by: dict[str, list[str]] = {}
        for eid, el in elements.items():
            o = ref_id(el.get("owner"))
            if o:
                self._owned_by.setdefault(o, []).append(eid)

    # ------------------------------------------------------------------ helpers
    def name_of(self, eid: str | None) -> str:
        if not eid:
            return "?"
        el = self.els.get(eid)
        if el:
            return el.get("declaredShortName") or el.get("shortName") or el.get("declaredName") or el.get("name") or eid[:8]
        return self.unit_names.get(eid, eid[:8])

    def arguments(self, expr: dict) -> list[str]:
        """Operands of an invocation. Prefer `argument`; otherwise the expressions owned by its parameters."""
        args = [a for a in ref_ids(expr.get("argument")) if a in self.els]
        if args:
            return args
        out = []
        for f in ref_ids(expr.get("ownedFeature")):
            if f == ref_id(expr.get("result")):
                continue
            for child in self._owned_by.get(f, []):
                if self.els[child].get("@type", "").endswith("Expression") or self.els[child].get("@type") in LITERAL_TYPES:
                    out.append(child)
        return out

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, eid: str | None, depth: int = 0) -> EvalResult:
        if not eid or depth > 25:
            return EvalResult(text="?", warnings=["expression too deep or missing"])
        el = self.els.get(eid)
        if el is None:
            return EvalResult(text="?", warnings=[f"expression element {eid} not in model"])
        t = el.get("@type", "")

        if t in LITERAL_TYPES:
            v = clean_float(el.get("value"))
            if t == "LiteralInfinity":
                v = math.inf
            txt = f'"{v}"' if t == "LiteralString" else str(v).lower() if isinstance(v, bool) else _fmt(v)
            return EvalResult(value=v, text=txt, literal_id=eid)

        if t == "NullExpression":
            return EvalResult(value=None, text="null")

        if t == "FeatureReferenceExpression":
            target = ref_id(el.get("referent"))
            name = self.name_of(target)
            target_el = self.els.get(target or "")
            # a unit reference (library unit, or anything with a short name like 'kg')
            if (target_el is None and target in self.unit_names) or (target_el and target_el.get("isLibraryElement")):
                return EvalResult(value=None, unit=name, text=name)
            if self.value_of_feature and target:
                r = self.value_of_feature(target)
                if r is not None and r.value is not None:
                    return EvalResult(value=r.value, unit=r.unit, text=name, warnings=list(r.warnings))
            return EvalResult(value=None, text=name)

        if t == "OperatorExpression":
            operator_ = el.get("operator")
            args = [self.evaluate(a, depth + 1) for a in self.arguments(el)]
            warns = [w for a in args for w in a.warnings]
            if operator_ == "[" and len(args) == 2:          # quantity with unit:  x [unit]
                unit = args[1].unit or args[1].text
                return EvalResult(value=args[0].value, unit=unit, text=f"{args[0].text} [{unit}]",
                                  literal_id=args[0].literal_id, warnings=warns)
            if operator_ == "-" and len(args) == 1:            # unary minus
                a = args[0]
                v = -a.value if isinstance(a.value, (int, float)) and not isinstance(a.value, bool) else None
                return EvalResult(value=v, unit=a.unit, text=f"-{a.text}", warnings=warns)
            if operator_ in (_BINARY | _COMPARE) and len(args) == 2:
                a, b = args
                text = f"{a.text} {operator_} {b.text}"
                v = None
                if _num(a.value) and _num(b.value):
                    if a.unit and b.unit and a.unit != b.unit and operator_ in ("+", "-", *_COMPARE):
                        warns.append(f"unit mismatch in '{text}' ({a.unit} vs {b.unit}); not evaluated")
                    else:
                        try:
                            v = (_BINARY | _COMPARE)[operator_](a.value, b.value)
                        except ZeroDivisionError:
                            warns.append(f"division by zero in '{text}'")
                unit = a.unit if operator_ in ("+", "-") else None
                return EvalResult(value=v, unit=unit, text=text, warnings=warns)
            text = f"{operator_}({', '.join(a.text for a in args)})"
            return EvalResult(value=None, text=text, warnings=warns + [f"operator '{operator_}' not evaluated"])

        if t in ("InvocationExpression", "Expression", "BooleanExpression", "Invariant", "ConstraintUsage"):
            res = ref_id(el.get("result"))
            # a constraint body: the last owned expression is the constraint's result
            owned = [c for c in self._owned_by.get(eid, []) if c != res]
            exprs = [c for c in owned if self.els[c].get("@type", "").endswith("Expression") or self.els[c].get("@type") in LITERAL_TYPES]
            for f in ref_ids(el.get("ownedFeature")):
                for c in self._owned_by.get(f, []):
                    if self.els[c].get("@type", "").endswith("Expression"):
                        exprs.append(c)
            if exprs:
                return self.evaluate(exprs[-1], depth + 1)
            return EvalResult(text=el.get("declaredName") or t, warnings=[f"{t} body not found"])

        return EvalResult(text=t, warnings=[f"unsupported expression type {t}"])


def clean_float(v):
    """Flexo returns decimals through a 32-bit float (Jena `lit.float`), so 9.8 comes back as
    9.800000190734863. Snap such values back to the 7-significant-digit number they came from."""
    if isinstance(v, float) and v not in (0.0,) and v == v and abs(v) != float("inf"):
        short = float(f"{v:.7g}")
        if abs(v - short) <= 1e-7 * abs(short):   # float32 rel. error <= 6e-8
            return short
    return v


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fmt(v) -> str:
    return repr(v) if isinstance(v, float) else str(v)
