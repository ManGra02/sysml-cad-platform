"""Guardrails -- the fixed safety limits around the agent's own decisions.

The agent decides per part, on the fly, WHAT matters (the rules: which property, which
check, how strict, critical or not -- see profile.py). This module only enforces that
those rules are applied correctly and that the agent cannot talk its way past them:

  * a part of a different kind is never a candidate (function gate)
  * critical rules (interfaces, fits) cannot be relaxed, and stay within MAX_CRITICAL_TOL_PCT
  * no rule can be relaxed beyond MAX_TOL_PCT
  * a part is only "fits" when every critical value could actually be checked
  * PLM records that contradict their own geometry are flagged "suspicious", never "fits"

Pure Python, no LLM and no I/O: same input, same verdict.
"""

import math
import re

MAX_TOL_PCT = 30          # no rule is ever widened beyond this
MAX_CRITICAL_TOL_PCT = 2  # interfaces and fits stay this tight, whatever the agent proposes
SAME_GROUP_SIM = 0.9      # function similarity: same job, different kind (bolt for a screw)
UNKNOWN = 0.5             # score of a value the part does not state
MIN_VERIFIED = 0.4        # share of the rules that must be checkable at all
PLAUSIBLE_PCT = 5         # PLM values may differ this much from the geometry before it is flagged
CHECKS = ("exact", "within", "at_least", "at_most", "similar")
STATUS_ORDER = {"fits": 0, "unverified": 1, "suspicious": 2, "fails": 3}


# -- small helpers -------------------------------------------------------------
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


# -- the agent's rules, made safe -----------------------------------------------
def make_rule(raw):
    """A rule proposed by the agent -> a rule the guardrails accept (or None if unusable).
    Tolerances are capped; ``capped`` tells the agent its proposal was too loose."""
    check = str(raw.get("check", "")).strip().lower()
    attr = snake(raw.get("attribute", ""))
    value = raw.get("value")
    if check not in CHECKS or not attr or value in (None, ""):
        return None
    critical = bool(raw.get("critical"))
    tol = max(num(raw.get("tolerance_pct")) or 0.0, 0.0)
    limit = MAX_CRITICAL_TOL_PCT if critical else MAX_TOL_PCT
    capped = check == "within" and tol > limit
    if check != "within":
        tol = 0.0
    return {"attribute": attr, "check": check, "value": norm_val(value), "critical": critical,
            "tolerance_pct": min(tol, limit), "capped": capped, "reason": str(raw.get("reason", ""))}


def relax(rule, tolerance_pct):
    """The agent wants a looser rule. Returns (new rule, None) or (None, refusal)."""
    if rule["critical"]:
        return None, "%s is critical (%s) and cannot be relaxed" % (rule["attribute"], rule["reason"] or "interface/fit")
    if rule["check"] != "within":
        return None, "%s is a %s check; only 'within' checks have a tolerance" % (rule["attribute"], rule["check"])
    tol = num(tolerance_pct)
    if tol is None or tol <= rule["tolerance_pct"]:
        return None, "the new tolerance must be larger than %g %%" % rule["tolerance_pct"]
    if tol > MAX_TOL_PCT:
        return None, "%g %% is beyond the limit of %d %%" % (tol, MAX_TOL_PCT)
    return {**rule, "tolerance_pct": tol}, None


# -- one rule against one value ----------------------------------------------------
def _apply(rule, cv):
    """-> (score 0..1, ok, needs_pct): needs_pct = tolerance that would make it pass, None if none can."""
    rv, check = rule["value"], rule["check"]
    rn, cn = num(rv), num(cv)
    if check == "similar":
        if rn is not None and cn is not None:
            s = 1.0 - min(abs(cn - rn) / max(abs(rn), 1e-9), 1.0)
        else:
            s = 1.0 if str(rv) == str(cv) else (0.6 if tokens(rv) & tokens(cv) else jaccard(rv, cv))
        return s, True, 0                                  # "similar" ranks, it never excludes
    if rn is None or cn is None:                           # words: exact match only
        same = str(rv).lower() == str(cv).lower()
        return (1.0 if same else 0.0), same, (0 if same else None)
    if check == "at_least":
        return (1.0, True, 0) if cn >= rn - 1e-9 else (0.0, False, None)
    if check == "at_most":
        return (1.0, True, 0) if cn <= rn + 1e-9 else (0.0, False, None)
    dev = abs(cn - rn) / max(abs(rn), 1e-9)
    tol = 0.0 if check == "exact" else rule["tolerance_pct"] / 100
    if dev <= tol + 1e-9:
        return (1.0 if dev < 1e-9 else 1.0 - 0.5 * dev / tol), True, 0
    fixable = check == "within" and not rule["critical"]
    return max(0.0, 1.0 - dev), False, (math.ceil(dev * 100) if fixable else None)


def function_similarity(category, cand_category, groups):
    if category and category == cand_category:
        return 1.0
    g = groups.get(category)
    if category and cand_category and g is not None and g == groups.get(cand_category):
        return SAME_GROUP_SIM
    return 0.0


def evaluate(profile, rules, cand, groups):
    """One PLM part against the agent's rules. None = a different kind of part (never a candidate)."""
    fs = function_similarity(profile["category"], cand["category"], groups)
    if fs <= 0:
        return None
    weighted, weights = [2 * fs], [2]
    passed, failed, unknown, needs, blocked, verified = [], [], [], 0, False, 0
    for rule in rules:
        w = 2 if rule["critical"] else 1
        cv = cand["attrs"].get(rule["attribute"])
        if cv is None:
            unknown.append(rule["attribute"])
            weighted.append(w * UNKNOWN)
            weights.append(w)
            continue
        verified += 1
        score, ok, need = _apply(rule, cv)
        weighted.append(w * score)
        weights.append(w)
        text = "%s %s (needs %s %s)" % (rule["attribute"], _fmt(cv), rule["check"], _fmt(rule["value"]))
        if ok:
            passed.append(text)
        else:
            failed.append(text)
            if need is None:
                blocked = True
            else:
                needs = max(needs, need)
    critical_unknown = [r["attribute"] for r in rules if r["critical"] and r["attribute"] in unknown]
    if failed:
        status = "fails"
    elif critical_unknown or (rules and verified / len(rules) < MIN_VERIFIED):
        status = "unverified"
    else:
        status = "fits"
    issues = cand.get("plm_issues") or []
    if issues and status != "fails":
        status = "suspicious"
    return {"item_number": cand["item_number"], "name": cand["name"], "status": status,
            "score": round(sum(weighted) / sum(weights), 3),
            "function": "same kind" if fs == 1.0 else "same job, different kind",
            "passed": passed, "failed": failed, "unknown": unknown,
            "needs_tolerance_pct": None if (blocked or not failed) else needs,
            "plm_issues": issues}


def rank(results):
    return sorted((r for r in results if r), key=lambda r: (STATUS_ORDER[r["status"]], -r["score"]))


# -- is the PLM record consistent with itself? --------------------------------------
def plausibility(record, spec, extents):
    """Contradictions inside one PLM record: what the name/description say vs the PLM fields vs the
    measured CAD geometry. Only hard contradictions -- a nominal length without the head is fine,
    a 300 mm dimension on a part whose geometry is 60 mm long is not."""
    issues = []
    size = extents[0] if extents else None
    if size:
        for k, v in spec["attrs"].items():
            n = num(v)
            if k.endswith("_mm") and n is not None and n > size * (1 + PLAUSIBLE_PCT / 100) + 0.5:
                issues.append("%s says %g mm, but the whole CAD model is only %g mm" % (k, n, size))
        thread = re.match(r"m(\d+(?:\.\d+)?)", str(spec["attrs"].get("thread_size", "")).lower())
        if thread and len(extents) == 3 and float(thread.group(1)) > extents[1] * (1 + PLAUSIBLE_PCT / 100):
            issues.append("thread %s does not fit into the CAD cross-section %g x %g mm"
                          % (thread.group(0).upper(), extents[1], extents[2]))
    for k, v in (record.get("attributes") or {}).items():
        a, b = num(v), num(spec["attrs"].get(snake(k)))
        if a is not None and b is not None and abs(a - b) > max(abs(a), abs(b)) * PLAUSIBLE_PCT / 100:
            issues.append("the name says %s = %g, the PLM attribute %s = %g" % (snake(k), b, k, a))
    said, field = spec.get("material", ""), (record.get("material") or "").lower()
    if said and field and not tokens(said) & tokens(field):
        issues.append("material: the name/description say '%s', the PLM field says '%s'" % (said, field))
    return issues


def _fmt(v):
    return "%g" % v if isinstance(v, float) else str(v)
