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
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .catalog import Catalog, load_catalog
from .mapping import Mapping
from .propose import DifflibProposer, Proposer, run
from .proposals import Proposal
from .verify import AdapterPool

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "fixtures" / "gold_mapping.yaml"


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


def load_gold(path: Path = GOLD) -> list[GoldEntry]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        GoldEntry(
            sysml_part=item["sysml_part"],
            attribute=item["attribute"],
            accept=tuple(item.get("accept") or ()),
            note=item.get("note", ""),
        )
        for item in data.get("gold") or []
    ]


def score(proposer: Proposer, gold: list[GoldEntry], catalog: Catalog) -> Score:
    """Rank the proposer's suggestions against the answer key.

    Deliberately run from an empty mapping: the question is what this proposer
    would suggest on a project where nothing is mapped yet, which is the only
    situation in which anybody reaches for one.
    """
    ranked, _dropped = run(
        proposer=proposer,
        top=3,
        catalog=catalog,
        mapping=Mapping(parts={}, attributes=[], digest="empty"),
    )

    by_attribute: dict[tuple[str, str], list[Proposal]] = {}
    for proposal in ranked:
        by_attribute.setdefault((proposal.sysml_part, proposal.attribute), []).append(proposal)
    for group in by_attribute.values():
        group.sort(key=lambda p: p.confidence, reverse=True)

    result = Score(proposer=getattr(proposer, "name", "?"), gold_entries=len(gold))
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


def report(scores: list[Score], gold: list[GoldEntry]) -> int:
    print(f"\ngold set     : {len(gold)} attribute(s), "
          f"{sum(len(g.accept) for g in gold)} accepted answer(s)")
    if len(gold) < 8:
        print("               TOO SMALL TO SEPARATE PROPOSERS -- publish "
              "models/gearbox.sysml\n               and extend the set before "
              "reading anything into a difference.")

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
    parser.add_argument("--ai", action="store_true",
                        help="include the AI proposer (needs credentials)")
    args = parser.parse_args(argv)

    gold = load_gold()
    catalog = load_catalog(pool=AdapterPool())

    proposers: list[Proposer] = [DifflibProposer()]
    if args.ai:
        from .propose_ai import ClaudeProposer
        proposers.append(ClaudeProposer())

    return report([score(p, gold, catalog) for p in proposers], gold)


if __name__ == "__main__":
    raise SystemExit(main())
