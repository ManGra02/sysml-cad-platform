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
import re
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Protocol

from .catalog import Catalog, CatalogAttribute, CatalogPart, load_catalog
from .extract import load as load_requirements
from .gates import MappingCheck, check_entry
from .mapping import Mapping, load_mapping
from .model import Requirement
from .proposals import Proposal, add, load_proposals, merged_mapping, save_proposals
from .units import ureg
from .verify import AdapterPool, _leaf

#: Which measurement can stand for which kind of quantity. The dimension is the
#: hard filter: whatever the names suggest, a length attribute is never proposed
#: against `mass`. Getting a wrong-but-plausible number is the failure this
#: whole project is built to avoid, and a proposer is where it would start.
_BY_DIMENSION = {
    ureg.mm.dimensionality: ("bbox_size",),
    ureg.kg.dimensionality: ("mass",),
    (ureg.mm**3).dimensionality: ("volume",),
    ureg.dimensionless.dimensionality: ("face_count",),
}

#: Which axis a named dimension is measured along. A convention, not a fact --
#: which is why every proposal that uses it says so in its rationale, and why
#: `mapping.yaml` carries the same warning under `note`.
_AXIS_BY_NAME = {
    "length": "X", "long": "X", "depth": "X",
    "width": "Y", "breadth": "Y",
    "height": "Z", "thickness": "Z", "tall": "Z",
}


class Proposer(Protocol):
    """Anything that can suggest mappings. The AI is one of these, not a
    special case: same input, same output, same gates, same scoreboard."""

    name: str

    def propose(self, catalog: Catalog) -> list[Proposal]:
        ...


# --------------------------------------------------------------------------
# Name handling
# --------------------------------------------------------------------------

def normalise(name: str) -> str:
    """`motorHousing`, `motor_housing`, `MOTOR_HOUSING` -> `motor housing`.

    The three naming conventions this project spans -- SysML camelCase, Python
    module snake_case, CAD parameter SCREAMING_CASE -- describe the same things
    in different clothes, and a proposer that could not see through that would
    be useless on its first real model.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = re.sub(r"[_\-./#]+", " ", spaced)
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

            methods = [
                m for m in target.methods
                if allowed is None or m in allowed
            ]
            if not methods:
                continue

            # The part's own name, and its definition's -- `motorHousing` may be
            # typed by `Housing`, and the CAD object is often named after one or
            # the other. Which of the two matched goes into the rationale: a
            # proposal that misstates its own evidence is worse than one that
            # gives none, because it survives review it should not survive.
            part_score, matched_on = max(
                (similarity(part.name, target.name), part.name),
                (similarity(part.definition, target.name) if part.definition else 0.0,
                 part.definition),
            )

            for method in methods:
                evidence, why = self._attribute_evidence(attribute, target, method)
                confidence = round(0.6 * part_score + 0.4 * evidence, 3)
                if confidence < self.threshold:
                    continue

                args = {}
                if method == "bbox_size":
                    axis = _AXIS_BY_NAME.get(normalise(attribute.name).split()[-1])
                    if axis is None:
                        continue    # no idea which axis; guessing is the bug
                    args = {"axis": axis}

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
                        f"name similarity {part_score:.2f} between {matched_on!r} "
                        f"and {target.name!r}; {why}"
                        + (f"; {attribute.name} taken along {args['axis']} by naming "
                           f"convention, not from the model" if args else "")
                    ),
                    proposed_by=self.name,
                ))
        return candidates

    def _attribute_evidence(self, attribute, target, method) -> tuple[float, str]:
        """How much the CAD side says about *this attribute*, beyond the object.

        A named parameter is the strongest signal there is -- `LENGTH_MM` on a
        script is a deliberate statement by whoever wrote it. A method whose name
        matches the attribute is the next best.
        """
        best, why = 0.0, "no attribute-level evidence, object name only"

        for parameter in target.parameters:
            score = similarity(attribute.name, re.sub(r"_(MM|KG|DEG|G_PER_CM3)$", "", parameter))
            if score > best:
                best, why = score, f"parameter {parameter} matches {attribute.name!r} ({score:.2f})"

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
        merged = merged_mapping(mapping, candidate)
        check = check_entry(merged.attributes[-1], merged, catalog, requirements, pool)
        if check.verdict == "invalid":
            dropped.append((candidate, check))
        else:
            kept.append(candidate)
    return kept, dropped


def already_mapped(mapping: Mapping) -> set[tuple[str, str]]:
    return {(e.sysml_part, e.attribute) for e in mapping.attributes if e.usable}


def run(
    proposer: Proposer | None = None,
    top: int = 1,
    catalog: Catalog | None = None,
    mapping: Mapping | None = None,
) -> tuple[list[Proposal], list[tuple[Proposal, MappingCheck]]]:
    """Propose, gate, and rank -- without storing anything."""
    proposer = proposer or DifflibProposer()
    pool = AdapterPool()
    catalog = catalog or load_catalog(pool=pool)
    mapping = mapping or load_mapping()
    requirements = {
        (r.requirement_id, _leaf(r.subject)): r for r in load_requirements()
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

def list_report() -> int:
    proposals = load_proposals()
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

    if dropped:
        print("\n  rejected by a gate (not stored):")
        for candidate, check in dropped:
            reason = next(
                (p.detail for p in check.problems if p.verdict == "invalid"), "?"
            )
            print(f"    {candidate.sysml_part}.{candidate.attribute} -> "
                  f"{candidate.cad_object} via {candidate.method}: {reason}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.propose",
        description="Suggest mapping entries (SRS FREQ-4). Nothing is applied; "
                    "confirm with `python -m sysmlcad.confirm`.",
    )
    parser.add_argument("--list", action="store_true", help="show the stored proposals")
    parser.add_argument("--ai", action="store_true",
                        help="ask Claude instead of the stdlib baseline "
                             "(needs `pip install anthropic` and credentials)")
    parser.add_argument("--top", type=int, default=1,
                        help="how many candidates to keep per attribute (default 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print candidates without storing them")
    args = parser.parse_args(argv)

    if args.list:
        return list_report()

    proposer: Proposer = DifflibProposer()
    if args.ai:
        from .propose_ai import ClaudeProposer
        proposer = ClaudeProposer()

    kept, dropped = run(proposer=proposer, top=args.top)
    if getattr(proposer, "dropped", None):
        print("\n  the proposer named things that do not exist "
              "(dropped before gating):")
        for reason in proposer.dropped:
            print(f"    {reason}")
    stored = 0
    if not args.dry_run and kept:
        proposals, stored = add(load_proposals(), kept)
        save_proposals(proposals)
    return report(kept, dropped, stored)


if __name__ == "__main__":
    raise SystemExit(main())
