"""Mapping proposals: the interface, and a baseline that needs no AI.

SRS FREQ-4 wants candidate mappings suggested rather than typed by hand.
This module defines what a proposer *is* and ships one that uses nothing but
`difflib` from the standard library. The AI proposer arrives later, behind the
same interface and scored on the same gold set.

WHY THE DUMB ONE FIRST
----------------------
Without a baseline there is no way to answer "does the AI help?". A hit rate of
80% sounds convincing until a stdlib string matcher scores 75% on the same data,
at no cost and with no API key. The baseline is what turns that claim into a
measurement -- and it doubles as the offline fallback, so CI never needs
credentials.

WHAT A PROPOSER MAY NOT DO
--------------------------
Write to `mapping.yaml`, or influence a verdict. Candidates land in
`proposals.yaml` with `status: proposed`, and reach the mapping only through
`python -m sysmlcad.confirm`, which re-gates them and records a human's name
(FREQ-5). Every candidate is gated *before* it is even stored: a proposal that
cannot pass a machine check has no business taking up a human's attention.
"""

from __future__ import annotations

import argparse
import sys
import re
from importlib import import_module
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Protocol

from .catalog import Catalog, CatalogAttribute, CatalogPart, load_catalog
from .extract import from_capture
from .project import Project, UnknownProject, add_project_argument, load_project
from .gates import PART_CONFLICT, MappingCheck, check_proposal
from .mapping import Mapping, load_mapping
from .model import Requirement
from .proposals import Proposal, add, load_proposals, save_proposals
from .units import ureg
from .verify import AdapterPool, _leaf

#: Which measurement can stand for which kind of quantity. The dimension is the
#: hard filter: whatever the names suggest, a length attribute is never proposed
#: against `mass`. Getting a wrong-but-plausible number is the failure this
#: whole project is built to avoid, and a proposer is where it would start.
_BY_DIMENSION = {
    ureg.mm.dimensionality: ("bbox_size", "cylinder_radius"),
    ureg.kg.dimensionality: ("mass",),
    (ureg.mm**3).dimensionality: ("volume",),
    ureg.dimensionless.dimensionality: ("face_count",),
}

#: A `cylinder_radius` is only offered for an attribute whose name ends in
#: "radius" -- a length or a thickness is not one, whatever the part's bores
#: measure. A name that also says "bore" or "hole" narrows it to a bore, so a
#: shaft or a fillet on the same part cannot answer for it.
_RADIUS_WORD = "radius"
_BORE_WORDS = {"bore", "hole"}

#: How much a matching parameter counts for a *measurement* of the same object.
#: Less than for the parameter itself: `LENGTH_MM` says the object has a length,
#: and a bounding box is only an approximation of it -- the parameter IS it.
#: So when both are possible the parameter ranks first, and the bounding box
#: stays a candidate below it.
_PARAMETER_SUPPORT = 0.8

#: A parameter is only proposed as the attribute when every word of its name is
#: accounted for by the part and the attribute. `HOUSING_LENGTH_MM` for the
#: cover's length would be a plausible number from a different feature.
_PARAMETER_EXACT = 1.0

#: Which axis a named dimension is measured along comes from the catalogue --
#: the project's `axes:` over `project.DEFAULT_AXES`. A convention, not a fact,
#: which is why every proposal that uses it says so in its rationale.


class Proposer(Protocol):
    """Anything that can suggest mappings. The AI is one of these, not a
    special case: same input, same output, same gates, same scoreboard."""

    name: str

    def propose(self, catalog: Catalog) -> list[Proposal]:
        ...


#: LLM backends, imported lazily -- each needs an SDK that `requirements.txt`
#: deliberately does not carry, and naming one here must not make CI need a key.
#: Adding a backend is one row plus one `_ask`; see `propose_ai.LlmProposer`.
AI_PROPOSERS: dict[str, tuple[str, str]] = {
    "openai": (".propose_openai", "OpenAIProposer"),
}


def build_proposer(which: str | None = None) -> Proposer:
    """`None` -> the stdlib baseline; a name from `AI_PROPOSERS` -> that model.

    The baseline is the default everywhere on purpose: it needs no key, no
    server and no network, so every path through this module stays runnable
    without credentials.
    """
    if not which:
        return DifflibProposer()
    if which not in AI_PROPOSERS:
        raise SystemExit(
            f"unknown AI backend {which!r}. Available: "
            f"{', '.join(sorted(AI_PROPOSERS))}"
        )
    module_name, class_name = AI_PROPOSERS[which]
    module = import_module(module_name, __package__)
    return getattr(module, class_name)()


# --------------------------------------------------------------------------
# Name handling
# --------------------------------------------------------------------------

def words(name: str) -> set[str]:
    return set(normalise(name).split())


def cad_identity(target) -> set[str]:
    """The words that identify a CAD target: the file it lives in and the node.

    `fixtures/step/gearbox.step#Housing` is identified by *gearbox* and
    *Housing* together -- the directories are storage, not identity, and the
    node name alone is not enough because two files can both contain a
    `Housing`.
    """
    reference = target.reference
    node = reference.split("#", 1)[1] if "#" in reference else ""
    stem = reference.split("#", 1)[0].rsplit("/", 1)[-1]
    for suffix in (".step", ".stp", ".py"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return words(stem) | words(node)


def identity_score(part, target) -> float:
    """How well a SysML part and a CAD object identify the *same thing*.

    Symmetric on purpose, unlike `similarity`: a word on either side that the
    other cannot account for counts against the match. That is what tells
    `Gearbox::housing` from `motor_housing` -- both contain "housing", and only
    one accounts for the rest.

    Learned from a measurement, not assumed: with containment scoring alone the
    baseline mapped all four gearbox housing attributes onto the motor housing
    of a different model, confidently and wrongly.
    """
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


def normalise(name: str) -> str:
    """`motorHousing`, `motor_housing`, `MOTOR_HOUSING` -> `motor housing`.

    The three naming conventions this project spans -- SysML camelCase, Python
    module snake_case, CAD parameter SCREAMING_CASE -- describe the same things
    in different clothes, and a proposer that could not see through that would
    be useless on its first real model.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = re.sub(r"[_\-./#:]+", " ", spaced)
    spaced = re.sub(r"\s+", " ", spaced)
    return spaced.strip().lower()


def similarity(left: str, right: str) -> float:
    """0..1 over normalised names, with containment treated generously.

    `Housing` inside `motor housing` is a strong signal that plain edit distance
    scores poorly, and it is the single most common shape of the real problem:
    the CAD name is the SysML name with the assembly's name in front of it.
    """
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


def _parameter_words(name: str) -> set[str]:
    """The words a parameter name speaks, without its unit suffix or its container.

    `LENGTH_MM` -> {length}; `Params.Length` -> {length}; `Pad.Length` ->
    {length}. A FreeCAD spreadsheet or feature label is where the value is
    kept, not what it is about -- `Params` would otherwise be a word the part
    can never account for.
    """
    bare = re.sub(r"_(MM|KG|DEG|G_PER_CM3)$", "", name)
    if "." in bare:
        bare = bare.rsplit(".", 1)[1]
    return words(bare)


# --------------------------------------------------------------------------
# The baseline
# --------------------------------------------------------------------------

class DifflibProposer:
    """Name similarity plus a dimension filter. No dependencies, no network.

    Scores two things and combines them: how much the CAD object's name looks
    like the part's, and how much evidence there is for the attribute -- a named
    parameter that matches it, or a measurement method that shares its name.
    """

    name = "baseline:difflib"

    #: Below this, a suggestion is noise rather than a candidate.
    threshold = 0.35

    def __init__(self, threshold: float | None = None):
        if threshold is not None:
            self.threshold = threshold

    def propose(self, catalog: Catalog) -> list[Proposal]:
        out: list[Proposal] = []
        for part in catalog.parts:
            for attribute in part.attributes:
                out.extend(self._for_attribute(catalog, part, attribute))
        return sorted(out, key=lambda p: p.confidence, reverse=True)

    def _for_attribute(
        self, catalog: Catalog, part: CatalogPart, attribute: CatalogAttribute
    ) -> list[Proposal]:
        dimension = attribute.dimensionality
        allowed = _BY_DIMENSION.get(dimension) if dimension is not None else None

        candidates: list[Proposal] = []
        for target in catalog.targets:
            if not target.addressable:
                continue

            # Does this CAD object identify the same thing as this part? Judged
            # on the qualified name against the file-plus-node, so that a second
            # published model cannot steal the match with a shared word.
            part_score = identity_score(part, target)
            matched_on = part.qualified

            if "parameter" in target.methods:
                candidates.extend(
                    self._parameter_candidates(part, attribute, target, part_score)
                )

            methods = [
                m for m in target.methods
                if m != "parameter" and (allowed is None or m in allowed)
            ]

            for method in methods:
                evidence, why = self._attribute_evidence(part, attribute, target, method)
                # Identity dominates, and deliberately so: a parameter named
                # exactly after the attribute is worth nothing if it sits on the
                # wrong object. Attribute evidence breaks ties between objects
                # that identify equally well -- it does not overrule them.
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

                candidates.append(Proposal(
                    id="",
                    sysml_part=part.name,
                    attribute=attribute.name,
                    adapter=target.adapter,
                    cad_object=target.reference,
                    method=method,
                    args=args,
                    confidence=confidence,
                    rationale=(
                        f"identity match {part_score:.2f} between {matched_on!r} "
                        f"and {target.reference!r}; {why}"
                        + (f"; {attribute.name} taken along {args['axis']} by the "
                           f"project's axis convention, not from the model"
                           if "axis" in args else "")
                        + (f"; the name says bore, so only a hole counts"
                           if "kind" in args else "")
                    ),
                    proposed_by=self.name,
                ))
        return candidates

    def _parameter_candidates(
        self, part: CatalogPart, attribute: CatalogAttribute, target, part_score: float
    ) -> list[Proposal]:
        """A named parameter that states this attribute, proposed as the attribute.

        Two conditions, both hard. The name: every word of it is accounted for
        by the part and the attribute, and the attribute's own words all appear
        in it -- `BORE_RADIUS_MM` for `boreRadius`, never for `length`. The
        dimension: the parameter's quantity has the attribute's, so a
        dimensionless spreadsheet cell never stands for a length. An attribute
        whose type is unknown gets no parameter candidate: there is nothing to
        hold the parameter's dimension against.
        """
        dimension = attribute.dimensionality
        if dimension is None:
            return []
        claimed = words(part.name) | words(part.package) | words(attribute.name)
        wanted = words(attribute.name)

        out: list[Proposal] = []
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
                id="",
                sysml_part=part.name,
                attribute=attribute.name,
                adapter=target.adapter,
                cad_object=target.reference,
                method="parameter",
                args={"name": name},
                confidence=confidence,
                rationale=(
                    f"identity match {part_score:.2f} between {part.qualified!r} "
                    f"and {target.reference!r}; the named parameter {name} "
                    f"({value:~P}) states {part.name}.{attribute.name} -- a "
                    f"stated dimension, not a measurement of the shape"
                ),
                proposed_by=self.name,
            ))
        return out

    def _attribute_evidence(self, part, attribute, target, method) -> tuple[float, str]:
        """How much the CAD side says about *this attribute*, beyond the object.

        A named parameter is the strongest signal there is -- `LENGTH_MM` on a
        script is a deliberate statement by whoever wrote it. A method whose name
        matches the attribute is the next best.

        Scored by precision: every word of the parameter name has to be
        accounted for by the part and the attribute it is claimed to measure.
        `HOUSING_LENGTH_MM` says "length" *and* "housing", so it is evidence for
        the housing's length and only half-evidence for the cover's -- the word
        the cover cannot explain is the whole point.
        """
        best, why = 0.0, "no attribute-level evidence, object name only"
        claimed = words(part.name) | words(part.package) | words(attribute.name)

        for parameter in target.parameters:
            spoken = _parameter_words(parameter)
            if not spoken:
                continue
            score = _PARAMETER_SUPPORT * len(spoken & claimed) / len(spoken)
            if score > best:
                best, why = score, (
                    f"parameter {parameter} accounted for by "
                    f"{part.name}.{attribute.name} ({score:.2f})"
                )

        method_score = similarity(attribute.name, method)
        if method_score > best:
            best = method_score
            # Only claim the method is named after the attribute when it plainly
            # is. `length` against `bbox_size` scores something, but calling that
            # a naming match would put a false statement in front of a reviewer.
            why = (
                f"the {method} measurement is named after the attribute"
                if method_score >= 0.6
                else f"only a weak name signal ({method_score:.2f}) for "
                     f"{attribute.name!r} on this object"
            )

        return best, why


# --------------------------------------------------------------------------
# Gating, before anything is stored
# --------------------------------------------------------------------------

def gate(
    candidates: list[Proposal],
    mapping: Mapping,
    catalog: Catalog,
    requirements: dict[tuple[str, str], Requirement],
    pool: AdapterPool,
) -> tuple[list[Proposal], list[tuple[Proposal, MappingCheck]]]:
    """Split candidates into the ones worth a human's time and the rest.

    Dropped candidates are returned rather than discarded: "the proposer
    suggested this and a gate rejected it" is how the proposer gets better, and
    silently swallowing it would hide a systematic mistake.
    """
    kept: list[Proposal] = []
    dropped: list[tuple[Proposal, MappingCheck]] = []

    for candidate in candidates:
        check = check_proposal(candidate, mapping, catalog, requirements, pool)
        if check.verdict == "invalid":
            dropped.append((candidate, check))
        else:
            kept.append(candidate)
    return kept, dropped


def already_mapped(mapping: Mapping) -> set[tuple[str, str]]:
    return {(e.sysml_part, e.attribute) for e in mapping.attributes if e.usable}


def run(
    project: Project,
    proposer: Proposer | None = None,
    top: int = 1,
    catalog: Catalog | None = None,
    mapping: Mapping | None = None,
) -> tuple[list[Proposal], list[tuple[Proposal, MappingCheck]]]:
    """Propose, gate, and rank for one project -- without storing anything."""
    proposer = proposer or DifflibProposer()
    pool = AdapterPool()
    catalog = catalog or load_catalog(project, pool=pool)
    mapping = mapping or load_mapping(project.mapping_path)
    requirements = {
        (r.requirement_id, _leaf(r.subject)): r for r in from_capture(project)
    }

    mapped = already_mapped(mapping)
    candidates = [
        c for c in proposer.propose(catalog)
        if (c.sysml_part, c.attribute) not in mapped
    ]

    kept, dropped = gate(candidates, mapping, catalog, requirements, pool)

    # Best `top` per attribute. The rest are real candidates too, but a review
    # queue nobody reads is worse than a short one somebody does.
    best: dict[tuple[str, str], list[Proposal]] = {}
    for candidate in kept:
        best.setdefault((candidate.sysml_part, candidate.attribute), []).append(candidate)
    ranked = [
        candidate
        for group in best.values()
        for candidate in sorted(group, key=lambda p: p.confidence, reverse=True)[:top]
    ]
    return sorted(ranked, key=lambda p: p.confidence, reverse=True), dropped


# --------------------------------------------------------------------------
# The commands
# --------------------------------------------------------------------------

def list_report(project: Project) -> int:
    proposals = load_proposals(project.proposals_path)
    if not proposals:
        print("\nno proposals yet -- `python -m sysmlcad.propose` makes some.\n")
        return 0

    print(f"\n{len(proposals)} proposal(s); "
          f"{sum(1 for p in proposals if p.pending)} pending\n")
    header = (f"{'id':<6} {'part.attribute':<28} {'cad object':<40} "
              f"{'method':<11} {'conf':>5}  status")
    print(header)
    print("-" * len(header))
    for p in proposals:
        print(f"{p.id:<6} {p.sysml_part + '.' + p.attribute:<28} "
              f"{p.cad_object:<40} {p.method:<11} {p.confidence:>5.2f}  {p.status}")
    print()
    for p in proposals:
        if p.pending and p.rationale:
            print(f"  {p.id}: {p.rationale}")
    print("\nconfirm one with:  python -m sysmlcad.confirm <id>\n")
    return 0


def report(kept: list[Proposal], dropped: list, stored: int) -> int:
    print(f"\n{len(kept)} candidate(s) past the gates, "
          f"{len(dropped)} rejected by them, {stored} new to the store\n")

    for candidate in kept:
        print(f"  {candidate.confidence:.2f}  {candidate.sysml_part}.{candidate.attribute}"
              f"  ->  {candidate.cad_object}  via {candidate.method}"
              f"({candidate.args or ''})")
        print(f"        {candidate.rationale}")

    # A candidate on another object than its part's mapped one is a conflict,
    # not a finding about that candidate -- one line per part says it, where
    # one line per candidate buried every other rejection under repetitions.
    conflicts: dict[str, list[str]] = {}
    others: list[tuple[Proposal, str]] = []
    for candidate, check in dropped:
        problem = next((p for p in check.problems if p.verdict == "invalid"), None)
        if problem is not None and problem.code == PART_CONFLICT:
            objects = conflicts.setdefault(candidate.sysml_part, [])
            if candidate.cad_object not in objects:
                objects.append(candidate.cad_object)
        else:
            others.append((candidate, problem.detail if problem else "?"))

    if others:
        print("\n  rejected by a gate (not stored):")
        for candidate, reason in others:
            print(f"    {candidate.sysml_part}.{candidate.attribute} -> "
                  f"{candidate.cad_object} via {candidate.method}: {reason}")
    if conflicts:
        count = len(dropped) - len(others)
        print(f"\n  {count} named another CAD object for a part that is already "
              f"mapped (not stored):")
        for part, objects in conflicts.items():
            print(f"    {part}: {', '.join(objects)}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.propose",
        description="Suggest mapping entries (SRS FREQ-4). Nothing is applied; "
                    "confirm with `python -m sysmlcad.confirm`.",
    )
    add_project_argument(parser)
    parser.add_argument("--list", action="store_true", help="show the stored proposals")
    parser.add_argument("--ai", nargs="?", const="openai", metavar="BACKEND",
                        help="ask a language model instead of the stdlib "
                             "baseline: openai (the default, any OpenAI-protocol "
                             "server). Needs that backend's SDK and credentials")
    parser.add_argument("--top", type=int, default=1,
                        help="how many candidates to keep per attribute (default 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print candidates without storing them")
    args = parser.parse_args(argv)

    try:
        project = load_project(args.project)
    except UnknownProject as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.list:
        return list_report(project)

    proposer = build_proposer(args.ai)

    kept, dropped = run(project, proposer=proposer, top=args.top)
    if getattr(proposer, "dropped", None):
        print("\n  the proposer named things that do not exist "
              "(dropped before gating):")
        for reason in proposer.dropped:
            print(f"    {reason}")
    stored = 0
    if not args.dry_run and kept:
        proposals, stored = add(load_proposals(project.proposals_path), kept)
        save_proposals(proposals, project.proposals_path)
    return report(kept, dropped, stored)


if __name__ == "__main__":
    raise SystemExit(main())
