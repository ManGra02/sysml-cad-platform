"""Understand what a part is -- and decide, for THIS part, what a replacement must fulfil.

The LLM acts as the engineer here: from whatever is known about the part (SysML attributes,
requirements, PLM description) it says what the part is and what it does, and it writes the
rules a replacement has to meet -- which property matters, how it is checked, how strict, and
whether it is critical (an interface or fit) -- each with a reason. Nothing per part type is
hard-coded; guardrails.py only enforces the rules safely.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.projects.cra import guardrails
from app.projects.cra.specs import ATTRIBUTE_NAMES

PROMPT = """You are a senior mechanical/electrical design engineer. Understand the part below and decide
what an existing part must fulfil to replace it in this design.

1. Say what the part is, its category (ONE lowercase singular noun, e.g. screw, pulley, bearing, battery,
   bracket, enclosure, tube, cable) and its function in a few words.
2. Collect its properties. Property names: """ + ATTRIBUTE_NAMES + """; anything else snake_case with a
   unit suffix. Values in mm, kg, kN, V, A, W or degrees. Only values that are given or that a named
   standard fixes for certain -- never guess.
3. Write the rules a replacement must meet, one per property that matters:
   - check "exact": interface values that must be identical (thread size, teeth, module, hole pattern, standard)
   - check "within" + tolerance_pct: sizes that may differ a little (overall length, envelope)
   - check "at_least": capacities (load, torque, current, voltage rating, strength)
   - check "at_most": limits (mass, size that must fit into a space)
   - check "similar": preferences that only rank (material when any comparable one is fine)
   critical = true for anything that decides whether it physically fits or works (bores, shafts, threads,
   mating interfaces, required ratings). Give every rule a short engineering reason.
4. Decide whether the item needs a CAD model at all: false for consumables (glue, threadlocker, sealant),
   software/firmware, services, bulk material and pure schematic nets; true for physical parts.
5. List open questions if something important is not known.

Part:
"""


class Rule(BaseModel):
    attribute: str = Field(description="property name, snake_case with unit suffix")
    check: Literal["exact", "within", "at_least", "at_most", "similar"]
    value: float | str
    tolerance_pct: float = Field(0, description="only for 'within'")
    critical: bool = False
    reason: str = Field(description="why this matters for this part")


class PartProfile(BaseModel):
    what_it_is: str = Field(description="one sentence: what the part is")
    category: str = Field(description="one lowercase singular noun")
    function: str = Field(description="what it does, a few words")
    material: str = ""
    needs_cad_model: bool = Field(True, description="false for consumables, software, services, schematic nets")
    properties: dict[str, float | str] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


def part_text(description, attributes=None):
    lines = [description.strip()] if description else []
    for k, v in (attributes or {}).items():
        lines.append("- %s: %s" % (k, v))
    return "\n".join(lines)


async def understand(llm, description, attributes=None):
    """-> (profile dict, rules accepted by the guardrails, notes on rules that were changed or dropped)."""
    raw = await llm.with_structured_output(PartProfile).ainvoke(PROMPT + part_text(description, attributes))
    if isinstance(raw, dict):
        raw = PartProfile(**raw)
    profile = {"what_it_is": raw.what_it_is, "category": raw.category.strip().lower(),
               "function": raw.function.strip().lower(), "material": raw.material.strip().lower(),
               "needs_cad_model": raw.needs_cad_model,
               "properties": {guardrails.snake(k): guardrails.norm_val(v) for k, v in raw.properties.items()},
               "open_questions": raw.open_questions}
    rules, notes = [], []
    for r in raw.rules:
        rule = guardrails.make_rule(r.model_dump())
        if rule is None:
            notes.append("dropped an unusable rule on %r" % r.attribute)
            continue
        if rule["capped"]:
            notes.append("%s: tolerance capped to %g %% by the guardrails" % (rule["attribute"], rule["tolerance_pct"]))
        rules.append(rule)
    return profile, rules, notes
