"""Verification: requirement + mapping + measurement -> verdict.

Answers only "is the design compliant?" -- whether the mapping is sound is gates.py.
Everything that cannot be checked becomes a gap, never a substituted value.
"""

from __future__ import annotations

from dataclasses import replace

from app.projects.bds.adapters import Unsupported
from app.projects.bds.extract import leaf
from app.projects.bds.model import (
    BadTolerance,
    DimensionMismatch,
    Run,
    RunContext,
    Verdict,
    parse_tolerance,
)


def _evaluate(req, entry, mapping, pool):
    part = mapping.part_for(entry)
    if part is None:
        raise Unsupported("no CAD object mapped for part %r" % entry.sysml_part)
    if not part.usable:
        # An unconfirmed part entry is not a weaker mapping, it is no mapping at all.
        raise Unsupported("part %r is mapped to %r with status %s, not confirmed -- not used in this run"
                          % (entry.sysml_part, part.cad_object, part.status))
    measured = pool.get(part.adapter).measure(part.cad_object, entry.method, entry.args)
    tolerance = parse_tolerance(entry.tolerance, req.limit)
    status, deviation = req.evaluate(measured, tolerance)
    return Verdict(requirement=req, measured=measured, status=status, deviation=deviation,
                   method="%s(%s) on %s:%s" % (entry.method, entry.args or {}, part.adapter, part.cad_object),
                   tolerance=tolerance)


def run(requirements, skipped, mapping, pool, context=None):
    """One workspace, one mapping, one model state.

    ``skipped``: requirements the extractor could not read -- they are gaps, and
    saying so is the difference between "0 not checked" being true and being a claim.
    """
    verdicts = []
    gaps = sorted(skipped)

    # Sorted, so the same model state gives the same report byte for byte.
    for req in sorted(requirements, key=lambda r: (r.requirement_id, r.subject)):
        subject = leaf(req.subject)
        entry = mapping.for_requirement(req.requirement_id, subject)
        if entry is None:
            unlinked = [e.attribute for e in mapping.attributes
                        if e.sysml_part == subject and e.usable and not e.requirement]
            if unlinked:
                gaps.append("%s: part %r has confirmed entries without a requirement (%s) -- link the "
                            "requirement in mapping.yaml" % (req.requirement_id, subject, ", ".join(unlinked)))
            else:
                gaps.append("%s: no mapping entry for part %r" % (req.requirement_id, subject))
            continue
        if not entry.usable:
            gaps.append("%s: mapping is %s, not confirmed -- not used in this run"
                        % (req.requirement_id, entry.status))
            continue

        # The measured attribute comes from the mapping (see extract.py).
        req = replace(req, prop=entry.attribute)
        try:
            verdicts.append(_evaluate(req, entry, mapping, pool))
        except Unsupported as exc:
            gaps.append("%s: %s" % (req.requirement_id, exc))
        except DimensionMismatch as exc:
            gaps.append("%s -- a mapping fault, see GET .../gates" % exc)
        except BadTolerance as exc:
            gaps.append("%s: %s -- a mapping fault, see GET .../gates" % (req.requirement_id, exc))

    context = replace(context or RunContext(), cad_adapter=pool.names, cad_state_id=pool.state_id,
                      mapping_digest=mapping.digest)
    return Run(context=context, verdicts=verdicts, gaps=gaps)
