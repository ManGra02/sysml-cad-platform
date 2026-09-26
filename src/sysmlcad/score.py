"""How good is a proposer? -- measured, not asserted.

ROADMAP, stage H: "Make it measurable: hit rate against a hand-mapped gold set.
Without that number there is no evidence the AI part saves any time at all."
This is that number, and it is deliberately built before the AI exists, so the
AI arrives into a scoreboard rather than bringing its own.

    python -m sysmlcad.score

WHICH NUMBER MATTERS
--------------------
Not hit rate. **False positives that survived the gates** -- a confident
suggestion that is wrong, sitting in a review queue looking exactly like the
right ones. A proposer that finds nine of ten mappings and invents one plausible
wrong one has not saved a human any work: they still have to check all ten.
That is why the report leads with it.

The scoring runs each proposer against an empty mapping, which is the situation
the proposer actually exists for: a new project, nothing mapped yet.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import yaml

from .catalog import Catalog, load_catalog
from .mapping import Mapping
from .project import Project, UnknownProject, add_project_argument, load_project
from .propose import AI_PROPOSERS, DifflibProposer, Proposer, build_proposer, run
from .proposals import Proposal
from .verify import AdapterPool



@dataclass(frozen=True)
class GoldEntry:
    """One attribute and every mapping that would be a correct answer for it.

    More than one, because the same part is measurable through the script and
    through its STEP export and the two agree -- penalising the second would be
    penalising the adapter seam for working.
    """

    sysml_part: str
    attribute: str
    accept: tuple[dict, ...] = ()
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.sysml_part, self.attribute)

    @property
    def expects_silence(self) -> bool:
        """No accepted answer means the correct behaviour is to propose nothing.

        Not an unfinished entry: some attributes genuinely have no counterpart
        in the CAD model, and a proposer that fills every gap with something
        plausible has saved nobody any work.
        """
        return not self.accept

    def matches(self, proposal: Proposal) -> bool:
        return any(
            answer.get("adapter") == proposal.adapter
            and answer.get("cad_object") == proposal.cad_object
            and answer.get("method") == proposal.method
            and (answer.get("args") or {}) == (proposal.args or {})
            for answer in self.accept
        )


@dataclass
class Score:
    proposer: str
    gold_entries: int = 0
    hit_at_1: int = 0
    hit_at_3: int = 0
    missed: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    spurious: list[str] = field(default_factory=list)

    @property
    def rate_at_1(self) -> float:
        return self.hit_at_1 / self.gold_entries if self.gold_entries else 0.0

    @property
    def rate_at_3(self) -> float:
        return self.hit_at_3 / self.gold_entries if self.gold_entries else 0.0


def load_gold(project: Project) -> list[GoldEntry]:
    """This project's answer key. Scoring against another model's parts would
    measure the proposer against distractors a real run never shows it."""
    data = yaml.safe_load(project.gold_path.read_text(encoding="utf-8")) or {}
    return [
        GoldEntry(
            sysml_part=item["sysml_part"],
            attribute=item["attribute"],
            accept=tuple(item.get("accept") or ()),
            note=item.get("note", ""),
        )
        for item in data.get("gold") or []
    ]


def score(project: Project, proposer: Proposer, gold: list[GoldEntry], catalog: Catalog) -> Score:
    """Rank the proposer's suggestions against the answer key.

    Deliberately run from an empty mapping: the question is what this proposer
    would suggest on a project where nothing is mapped yet, which is the only
    situation in which anybody reaches for one.
    """
    ranked, _dropped = run(
        project,
        proposer=proposer,
        top=3,
        catalog=catalog,
        mapping=Mapping(parts={}, attributes=[], digest="empty"),
    )
    return score_ranked(getattr(proposer, "name", "?"), gold, ranked)


def score_ranked(name: str, gold: list[GoldEntry], ranked: list[Proposal]) -> Score:
    """Score suggestions that have already been made.

    Split from `score()` so that one model answer -- one paid request -- can
    be stored and scored again, instead of asked for twice.
    """
    by_attribute: dict[tuple[str, str], list[Proposal]] = {}
    for proposal in ranked:
        by_attribute.setdefault((proposal.sysml_part, proposal.attribute), []).append(proposal)
    for group in by_attribute.values():
        group.sort(key=lambda p: p.confidence, reverse=True)

    result = Score(proposer=name, gold_entries=len(gold))
    expected = {entry.key for entry in gold}

    for entry in gold:
        suggestions = by_attribute.get(entry.key, [])

        if entry.expects_silence:
            if suggestions:
                result.false_positives.append(
                    f"{entry.sysml_part}.{entry.attribute}: suggested "
                    f"{suggestions[0].cad_object} via {suggestions[0].method}"
                    f"{suggestions[0].args or ''} at {suggestions[0].confidence:.2f}, "
                    f"but nothing can measure this attribute"
                )
            else:
                result.hit_at_1 += 1
                result.hit_at_3 += 1
            continue

        if not suggestions:
            result.missed.append(f"{entry.sysml_part}.{entry.attribute}: nothing suggested")
            continue
        if entry.matches(suggestions[0]):
            result.hit_at_1 += 1
        else:
            result.false_positives.append(
                f"{entry.sysml_part}.{entry.attribute}: top answer was "
                f"{suggestions[0].cad_object} via {suggestions[0].method}"
                f"{suggestions[0].args or ''} at {suggestions[0].confidence:.2f}"
            )
        if any(entry.matches(s) for s in suggestions[:3]):
            result.hit_at_3 += 1

    for key, suggestions in by_attribute.items():
        if key not in expected:
            result.spurious.append(
                f"{key[0]}.{key[1]}: {suggestions[0].cad_object} via "
                f"{suggestions[0].method} at {suggestions[0].confidence:.2f} "
                f"-- no gold entry for this attribute"
            )

    return result


def report(scores: list[Score], gold: list[GoldEntry], project: Project | None = None) -> int:
    if project is not None:
        print(f"\nproject      : {project.name}")
    print(f"{'' if project else chr(10)}gold set     : {len(gold)} attribute(s), "
          f"{sum(len(g.accept) for g in gold)} accepted answer(s)")
    if len(gold) < 8:
        print("               too small to separate proposers -- a model this "
              "size cannot\n               tell a language model from a string "
              "matcher; read the number as\n               a smoke test, not a "
              "measurement.")

    header = f"\n{'proposer':<22} {'hit@1':>10} {'hit@3':>10} {'wrong@1':>9} {'missed':>8}"
    print(header)
    print("-" * (len(header) - 1))
    for s in scores:
        print(f"{s.proposer:<22} {s.hit_at_1}/{s.gold_entries} "
              f"({s.rate_at_1:>3.0%}) {s.hit_at_3}/{s.gold_entries} "
              f"({s.rate_at_3:>3.0%}) {len(s.false_positives):>9} {len(s.missed):>8}")
    print("-" * (len(header) - 1))

    for s in scores:
        details = s.false_positives + s.missed + s.spurious
        if details:
            print(f"\n{s.proposer}:")
            for line in details:
                print(f"  {line}")

    print("\nThe column to watch is wrong@1: a confident wrong answer costs a "
          "human\nmore than a missing one, because it looks exactly like a right "
          "one.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.score",
        description="Score mapping proposers against the hand-mapped gold set.",
    )
    add_project_argument(parser)
    parser.add_argument("--ai", nargs="?", const="claude", metavar="BACKEND",
                        help=f"also score a language model: "
                             f"{', '.join(sorted(AI_PROPOSERS))}. Needs that "
                             f"backend's SDK and credentials")
    args = parser.parse_args(argv)

    try:
        project = load_project(args.project)
    except UnknownProject as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    gold = load_gold(project)
    catalog = load_catalog(project, pool=AdapterPool())

    # The baseline always runs: a model's number means nothing on its own, and
    # showing them side by side is the entire point of this command.
    proposers: list[Proposer] = [DifflibProposer()]
    if args.ai:
        proposers.append(build_proposer(args.ai))

    return report([score(project, p, gold, catalog) for p in proposers], gold, project)


if __name__ == "__main__":
    raise SystemExit(main())
