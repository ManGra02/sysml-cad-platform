"""How good is a proposer? -- measured against a hand-mapped gold set, not asserted.

The number that matters is not the hit rate but ``wrong@1``: a confident wrong answer
looks exactly like a right one, so a human still has to check everything. Each
proposer is scored from an empty mapping -- the situation it exists for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from app.projects.bds.mapping import empty_mapping
from app.projects.bds.propose import run
from app.projects.bds.workspace import BdsError


@dataclass(frozen=True)
class GoldEntry:
    """One attribute and every mapping that would be a correct answer. No accepted
    answer means the right behaviour is to propose nothing."""

    sysml_part: str
    attribute: str
    accept: tuple = ()
    note: str = ""

    @property
    def key(self):
        return (self.sysml_part, self.attribute)

    @property
    def expects_silence(self):
        return not self.accept

    def matches(self, proposal):
        return any(answer.get("adapter") == proposal.adapter
                   and answer.get("cad_object") == proposal.cad_object
                   and answer.get("method") == proposal.method
                   and (answer.get("args") or {}) == (proposal.args or {})
                   for answer in self.accept)


@dataclass
class Score:
    proposer: str
    gold_entries: int = 0
    hit_at_1: int = 0
    hit_at_3: int = 0
    missed: list = field(default_factory=list)
    false_positives: list = field(default_factory=list)
    spurious: list = field(default_factory=list)

    @property
    def rate_at_1(self):
        return self.hit_at_1 / self.gold_entries if self.gold_entries else 0.0

    @property
    def rate_at_3(self):
        return self.hit_at_3 / self.gold_entries if self.gold_entries else 0.0

    def to_dict(self):
        return {"proposer": self.proposer, "gold_entries": self.gold_entries,
                "hit_at_1": self.hit_at_1, "hit_at_3": self.hit_at_3,
                "rate_at_1": round(self.rate_at_1, 3), "rate_at_3": round(self.rate_at_3, 3),
                "wrong_at_1": len(self.false_positives), "missed": self.missed,
                "false_positives": self.false_positives, "spurious": self.spurious}


def load_gold(path):
    if not path.is_file():
        raise BdsError(404, "bds_no_gold", "No gold set at %s -- scoring needs gold_mapping.yaml" % path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [GoldEntry(sysml_part=item["sysml_part"], attribute=item["attribute"],
                      accept=tuple(item.get("accept") or ()), note=item.get("note", ""))
            for item in data.get("gold") or []]


def _top(suggestion):
    return "%s via %s%s at %.2f" % (suggestion.cad_object, suggestion.method, suggestion.args or "",
                                     suggestion.confidence)


def score_ranked(name, gold, ranked):
    """Score suggestions already made -- one paid model answer can be scored again."""
    by_attribute = {}
    for proposal in ranked:
        by_attribute.setdefault((proposal.sysml_part, proposal.attribute), []).append(proposal)
    for group in by_attribute.values():
        group.sort(key=lambda p: p.confidence, reverse=True)

    result = Score(proposer=name, gold_entries=len(gold))
    for entry in gold:
        suggestions = by_attribute.get(entry.key, [])
        label = "%s.%s" % entry.key
        if entry.expects_silence:
            if suggestions:
                result.false_positives.append("%s: suggested %s, but nothing can measure this attribute"
                                              % (label, _top(suggestions[0])))
            else:
                result.hit_at_1 += 1
                result.hit_at_3 += 1
            continue
        if not suggestions:
            result.missed.append("%s: nothing suggested" % label)
            continue
        if entry.matches(suggestions[0]):
            result.hit_at_1 += 1
        else:
            result.false_positives.append("%s: top answer was %s" % (label, _top(suggestions[0])))
        if any(entry.matches(s) for s in suggestions[:3]):
            result.hit_at_3 += 1

    expected = {entry.key for entry in gold}
    for key, suggestions in by_attribute.items():
        if key not in expected:
            result.spurious.append("%s.%s: %s -- no gold entry for this attribute" % (key + (_top(suggestions[0]),)))
    return result


async def score(proposer, gold, catalog, requirements, pool):
    ranked, _dropped = await run(proposer, catalog, empty_mapping(), requirements, pool, top=3)
    return score_ranked(getattr(proposer, "name", "?"), gold, ranked)
