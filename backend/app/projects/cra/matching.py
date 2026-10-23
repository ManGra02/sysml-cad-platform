"""Compare a required part with PLM parts -- by function and dimensions, not by name.

Pure Python, no LLM and no I/O: the LLM only reads names into specs (specs.py).
The rules are data (the sets below), so there is no if-statement per part type.

A spec is ``{"category", "type", "function", "material", "attrs": {name: value}}``.
Attribute names are snake_case with a unit suffix: ``bore_diameter_mm``.
"""

import math
import re

DEFAULT_TOL_PCT = 10   # how far a size may differ and still count as fitting
MAX_TOL_PCT = 30       # the agent may widen the tolerance up to here

EXACT_KEYS = {"thread_size", "teeth", "module_mm", "pressure_angle_deg", "standard"}      # must match exactly
MIN_KEYS = {"load_rating_kn", "load_capacity_kn", "torque_rating_nm", "strength_mpa"}      # part must be >= required
MAX_KEYS = {"mass_kg"}                                                                    # part must be <= required
STRICT_KEYS = {"bore_diameter_mm", "shaft_diameter_mm", "inner_diameter_mm", "diameter_mm"}  # fit-critical sizes
STRICT_TOL = 0.02      # these may differ by 2 percent at most, even when the tolerance is widened
SAME_GROUP_SIM = 0.9   # function score when the kind differs but does the same job (bolt vs screw)
WEIGHTS = {"function": 0.3, "dimensions": 0.5, "material": 0.2}
UNKNOWN = 0.5          # score for a value the part does not state
MIN_VERIFIED = 0.4     # at least this share of the required values must be checkable
REQ_SPECIAL = {"part_type", "function", "material"}   # requirement attributes that are not dimensions


def snake(name):
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", str(name).strip())
    return re.sub(r"_+", "_", s.replace(" ", "_").replace("-", "_")).lower()


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def norm_val(v):
    n = num(v)
    return n if n is not None else str(v).strip().lower()


def tokens(s):
    return set(re.findall(r"[a-z0-9]+", str(s).lower()))


def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


def empty_spec():
    return {"category": "", "type": "", "function": "", "material": "", "attrs": {}}


def requirement_text(attributes):
    """The words describing the required part ("pulley: transmits belt drive"), read by the LLM."""
    a = {snake(k): v for k, v in attributes.items()}
    ptype, func = str(a.get("part_type", "")).strip().lower(), str(a.get("function", "")).strip().lower()
    return f"{ptype}: {func}".strip(": ")


def requirement_spec(attributes, read):
    """SysML attributes + the LLM's reading of the requirement text (``read``) -> spec."""
    a = {snake(k): v for k, v in attributes.items()}
    ptype, func = str(a.get("part_type", "")).strip().lower(), str(a.get("function", "")).strip().lower()
    read = read or empty_spec()
    return {"category": read["category"] or (ptype.split()[-1] if ptype else ""),
            "type": ptype or read["type"], "function": func or read["function"],
            "material": str(a.get("material", "")).strip().lower(),
            "attrs": {k: norm_val(v) for k, v in a.items() if k not in REQ_SPECIAL and v not in (None, "")}}


def material_score(r, c):
    if not r or not c:
        return UNKNOWN
    if r == c:
        return 1.0
    return 0.6 if tokens(r) & tokens(c) else 0.0     # "steel" vs "stainless steel" shares a word


def function_score(req, cand, groups):
    rc, cc = req["category"], cand["category"]
    if rc and rc == cc:
        return 1.0
    if rc and cc and groups.get(rc) is not None and groups.get(rc) == groups.get(cc):
        return SAME_GROUP_SIM
    return 0.0


def compare(req, cand, tol, groups):
    """Score one PLM part against the requirement; None if it is a different kind of part.
    ``tol``: tolerance as a fraction (0.1 = 10 %)."""
    fs = function_score(req, cand, groups)
    if fs <= 0:
        return None
    fails, parts, verified, needs, blocked = [], [], 0, 0.0, False
    for k, rv in req["attrs"].items():
        cv = cand["attrs"].get(k)
        if cv is None:
            parts.append(UNKNOWN)                    # the part does not state it
            continue
        verified += 1
        rn, cn = num(rv), num(cv)
        if rn is not None and cn is not None:
            if k in MIN_KEYS or k in MAX_KEYS:
                good = cn >= rn - 1e-9 if k in MIN_KEYS else cn <= rn + 1e-9
                parts.append(1.0 if good else 0.0)
                if not good:
                    fails.append(f"{k} {cn:g} vs {rn:g}")
                    blocked = True
            else:
                dev = abs(cn - rn) / max(abs(rn), 1e-9)
                strict = k in STRICT_KEYS
                t = 0.0 if k in EXACT_KEYS else (min(tol, STRICT_TOL) if strict else tol)
                if dev <= t + 1e-9:
                    parts.append(1.0 if dev < 1e-9 else 1.0 - 0.5 * dev / t)
                else:
                    parts.append(max(0.0, 1.0 - dev))
                    fails.append(f"{k} {cn:g} vs {rn:g}")
                    if k in EXACT_KEYS or strict:
                        blocked = True                # widening the tolerance cannot fix this
                    else:
                        needs = max(needs, dev)
        elif k in EXACT_KEYS:
            same = str(cv).lower() == str(rv).lower()
            parts.append(1.0 if same else 0.0)
            if not same:
                fails.append(f"{k} {cv} vs {rv}")
                blocked = True
        else:
            parts.append(jaccard(rv, cv))            # words like head type: soft
    ms = material_score(req["material"], cand["material"])
    if ms == 0.0:
        fails.append(f"material {cand['material']} vs {req['material']}")
        blocked = True
    total = len(req["attrs"])
    if total and verified / total < MIN_VERIFIED:
        fails.append("too few values to check")
        blocked = True
    dim = sum(parts) / len(parts) if parts else UNKNOWN
    score = WEIGHTS["function"] * fs + WEIGHTS["dimensions"] * dim + WEIGHTS["material"] * ms
    return {"item_number": cand["item_number"], "name": cand["name"], "score": round(score, 3),
            "failures": fails, "passed": not fails,
            "needs_pct": None if blocked else (math.ceil(needs * 100) if fails else 0)}


def rank(req, cands, tolerance_pct, groups):
    """All PLM parts against one requirement -> best part and the three closest misses."""
    tol = max(float(tolerance_pct), 0.0) / 100
    results = [r for r in (compare(req, c, tol, groups) for c in cands) if r]
    passed = sorted((r for r in results if r["passed"]), key=lambda r: -r["score"])
    near = sorted((r for r in results if not r["passed"]), key=lambda r: (len(r["failures"]), -r["score"]))
    return {"best": ({"item_number": passed[0]["item_number"], "name": passed[0]["name"],
                      "score": passed[0]["score"]} if passed else None),
            "near_misses": [{"item_number": r["item_number"], "name": r["name"],
                             "failures": r["failures"], "needs_tolerance_pct": r["needs_pct"]}
                            for r in near[:3]],
            "checked": len(cands), "same_function": len(results),
            "passed": len(passed), "tolerance_pct": float(tolerance_pct)}
