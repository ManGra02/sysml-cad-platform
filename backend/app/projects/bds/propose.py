"""Mapping proposals: the proposer interface, and a baseline that needs no AI.

Without a baseline there is no way to answer "does the AI help?": a hit rate of 80%
sounds convincing until a string matcher scores 75% on the same data. The baseline
is that comparison, and the fallback when no model is configured.

A proposer may not write to mapping.yaml or influence a verdict. Candidates are gated
BEFORE they are stored -- one that cannot pass a machine check has no business taking
up a human's attention -- and reach the mapping only through confirm.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.projects.bds.gates import PART_CONFLICT, check_proposal
from app.projects.bds.proposals import Proposal
from app.projects.bds.units import ureg

#: Which measurement can stand for which kind of quantity -- the hard filter.
_BY_DIMENSION = {
    ureg.mm.dimensionality: ("bbox_size", "cylinder_radius"),
    ureg.kg.dimensionality: ("mass",),
    (ureg.mm**3).dimensionality: ("volume",),
    ureg.dimensionless.dimensionality: ("face_count",),
}

#: cylinder_radius only for an attribute whose name ends in "radius"; "bore"/"hole"
#: in the name narrows it to a bore.
_RADIUS_WORD = "radius"
_BORE_WORDS = {"bore", "hole"}

#: A matching parameter supports a MEASUREMENT of the same object less than it
#: supports itself: LENGTH_MM IS the length, a bounding box approximates it.
_PARAMETER_SUPPORT = 0.8
_PARAMETER_EXACT = 1.0


def normalise(name):
    """``motorHousing``, ``motor_housing``, ``Params.Length`` -> words in lower case."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = re.sub(r"[_\-./#:]+", " ", spaced)
    return re.sub(r"\s+", " ", spaced).strip().lower()


def words(name):
    return set(normalise(name).split())


def cad_identity(target):
    """The words that identify a CAD target: its document and its label.

    ``Gearbox#Body001`` labelled "Housing" is identified by *gearbox* and *housing* --
    the internal name is FreeCAD's counter, not identity.
    """
    document = target.reference.split("#", 1)[0]
    return words(document) | words(target.name)


def identity_score(part, target):
    """How well a SysML part and a CAD object identify the SAME thing. Symmetric: a word
    on either side the other cannot account for counts against the match -- that is
    what tells ``Gearbox::housing`` from ``motor_housing``."""
    left = words(part.package) | words(part.name) | words(part.definition)
    right = cad_identity(target)
    if not left or not right:
        return 0.0
    shared = left & right
    if not shared:
        return SequenceMatcher(None, " ".join(sorted(left)), " ".join(sorted(right))).ratio()
    precision = len(shared) / len(right)
    recall = len(shared) / len(left)
    return 2 * precision * recall / (precision + recall)


def similarity(left, right):
    """0..1 over normalised names, containment treated generously."""
    a, b = normalise(left), normalise(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    words_a, words_b = set(a.split()), set(b.split())
    if words_a & words_b:
        overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
        ratio = max(ratio, 0.55 + 0.45 * overlap)
    return ratio


def _parameter_words(name):
    """``LENGTH_MM`` / ``Params.Length`` / ``Pad.Length`` -> {length}: without unit
    suffix and without the sheet or feature that holds it."""
    bare = re.sub(r"_(MM|KG|DEG|G_PER_CM3)$", "", name)
    if "." in bare:
        bare = bare.rsplit(".", 1)[1]
    return words(bare)


class DifflibProposer:
    """Name similarity plus a dimension filter. No dependencies, no network."""

    name = "baseline:difflib"
    threshold = 0.35

    def __init__(self, threshold=None):
        if threshold is not None:
            self.threshold = threshold
        self.dropped = []

    async def propose(self, catalog):
        out = []
        for part in catalog.parts:
            for attribute in part.attributes:
                out.extend(self._for_attribute(catalog, part, attribute))
        return sorted(out, key=lambda p: p.confidence, reverse=True)

    def _for_attribute(self, catalog, part, attribute):
        dimension = attribute.dimensionality
        allowed = _BY_DIMENSION.get(dimension) if dimension is not None else None

        candidates = []
        for target in catalog.targets:
            if not target.addressable:
                continue
            part_score = identity_score(part, target)
            if "parameter" in target.methods:
                candidates.extend(self._parameter_candidates(part, attribute, target, part_score))

            for method in (m for m in target.methods if m != "parameter" and (allowed is None or m in allowed)):
                evidence, why = self._attribute_evidence(part, attribute, target, method)
                # Identity dominates: a parameter named exactly after the attribute is
                # worth nothing on the wrong object.
                confidence = round(0.75 * part_score + 0.25 * evidence, 3)
                if confidence < self.threshold:
                    continue

                args = {}
                named = normalise(attribute.name).split()
                if method == "bbox_size":
                    axis = catalog.axes.get(named[-1])
                    if axis is None:
                        continue    # no idea which axis; guessing is the bug
                    args = {"axis": axis}
                elif method == "cylinder_radius":
                    if named[-1] != _RADIUS_WORD:
                        continue    # a length is not a radius
                    if _BORE_WORDS & set(named):
                        args = {"kind": "hole"}

                rationale = "identity match %.2f between %r and %r; %s" % (
                    part_score, part.qualified, target.reference, why)
                if "axis" in args:
                    rationale += ("; %s taken along %s by the workspace's axis convention, not from the model"
                                  % (attribute.name, args["axis"]))
                if "kind" in args:
                    rationale += "; the name says bore, so only a hole counts"
                candidates.append(Proposal(
                    id="", sysml_part=part.name, attribute=attribute.name, adapter=target.adapter,
                    cad_object=target.reference, method=method, args=args, confidence=confidence,
                    rationale=rationale, proposed_by=self.name,
                ))
        return candidates

    def _parameter_candidates(self, part, attribute, target, part_score):
        """A named parameter that states this attribute, proposed as the attribute.

        Every word of its name is accounted for by part and attribute, the attribute's
        own words all appear in it, and its quantity has the attribute's dimension.
        """
        dimension = attribute.dimensionality
        if dimension is None:
            return []
        claimed = words(part.name) | words(part.package) | words(attribute.name)
        wanted = words(attribute.name)

        out = []
        for name, value in target.parameters.items():
            if getattr(value, "dimensionality", None) != dimension:
                continue
            spoken = _parameter_words(name)
            if not spoken or not wanted <= spoken:
                continue
            if len(spoken & claimed) / len(spoken) < _PARAMETER_EXACT:
                continue
            confidence = round(0.75 * part_score + 0.25 * 1.0, 3)
            if confidence < self.threshold:
                continue
            out.append(Proposal(
                id="", sysml_part=part.name, attribute=attribute.name, adapter=target.adapter,
                cad_object=target.reference, method="parameter", args={"name": name},
                confidence=confidence, proposed_by=self.name,
                rationale=("identity match %.2f between %r and %r; the named parameter %s (%s) states "
                           "%s.%s -- a stated dimension, not a measurement of the shape"
                           % (part_score, part.qualified, target.reference, name,
                              format(value, "~P"), part.name, attribute.name)),
            ))
        return out

    def _attribute_evidence(self, part, attribute, target, method):
        """How much the CAD side says about THIS attribute, beyond the object: a named
        parameter (scored by precision -- every word has to be accounted for), or a
        method named like the attribute."""
        best, why = 0.0, "no attribute-level evidence, object name only"
        claimed = words(part.name) | words(part.package) | words(attribute.name)
        for parameter in target.parameters:
            spoken = _parameter_words(parameter)
            if not spoken:
                continue
            score = _PARAMETER_SUPPORT * len(spoken & claimed) / len(spoken)
            if score > best:
                best, why = score, "parameter %s accounted for by %s.%s (%.2f)" % (
                    parameter, part.name, attribute.name, score)

        method_score = similarity(attribute.name, method)
        if method_score > best:
            best = method_score
            why = ("the %s measurement is named after the attribute" % method if method_score >= 0.6
                   else "only a weak name signal (%.2f) for %r on this object" % (method_score, attribute.name))
        return best, why


def gate(candidates, mapping, catalog, requirements, pool):
    """Split candidates into the ones worth a human's time and the rest (with reasons)."""
    kept, dropped = [], []
    for candidate in candidates:
        check = check_proposal(candidate, mapping, catalog, requirements, pool)
        if check.verdict == "invalid":
            dropped.append((candidate, check))
        else:
            kept.append(candidate)
    return kept, dropped


def already_mapped(mapping):
    return {(e.sysml_part, e.attribute) for e in mapping.attributes if e.usable}


async def run(proposer, catalog, mapping, requirements, pool, top=1):
    """Propose, gate and rank -- without storing anything -> (ranked, dropped)."""
    mapped = already_mapped(mapping)
    candidates = [c for c in await proposer.propose(catalog) if (c.sysml_part, c.attribute) not in mapped]
    kept, dropped = gate(candidates, mapping, catalog, requirements, pool)

    # Best `top` per attribute: a review queue nobody reads is worse than a short one.
    best = {}
    for candidate in kept:
        best.setdefault((candidate.sysml_part, candidate.attribute), []).append(candidate)
    ranked = [c for group in best.values()
              for c in sorted(group, key=lambda p: p.confidence, reverse=True)[:top]]
    return sorted(ranked, key=lambda p: p.confidence, reverse=True), dropped


def dropped_report(dropped):
    """Gate rejections, one line per part for part conflicts instead of per candidate."""
    out = []
    conflicts = {}
    for candidate, check in dropped:
        problem = next((p for p in check.problems if p.verdict == "invalid"), None)
        if problem is not None and problem.code == PART_CONFLICT:
            objects = conflicts.setdefault(candidate.sysml_part, [])
            if candidate.cad_object not in objects:
                objects.append(candidate.cad_object)
            continue
        out.append({"sysml_part": candidate.sysml_part, "attribute": candidate.attribute,
                    "cad_object": candidate.cad_object, "method": candidate.method,
                    "args": candidate.args, "reason": problem.detail if problem else "?"})
    for part, objects in conflicts.items():
        out.append({"sysml_part": part, "code": PART_CONFLICT,
                    "reason": "%s is already mapped; candidates named %s" % (part, ", ".join(objects))})
    return out
