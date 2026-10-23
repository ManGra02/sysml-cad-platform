"""LLM proposer: a language model suggests mappings, and nothing else.

Same input, same output type, same gates and the same scoreboard as the difflib
baseline. Once a candidate is confirmed nothing behaves differently because a model
suggested it -- which is what makes an AI safe to have here at all.

FOUR THINGS THAT KEEP IT HONEST
1. Structured output against a strict JSON schema, not prose.
2. Every field is checked against the catalogue (_verify): a model naming a CAD
   object that does not exist is dropped with the reason recorded.
3. Then the ordinary gates (propose.run).
4. Provenance on every candidate: model, prompt digest, response id.

The prompt (SYSTEM, INSTRUCTION) and the excerpt (render_catalog) are the
bidirectional-sync PoC's, unchanged -- they were tuned against measured failures of
real models (assembly measured for a component, wrong axis, exporter names).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from app.projects.bds.proposals import Proposal

SYSTEM = """\
You map systems-engineering model attributes onto CAD measurements.

You propose, a human confirms. Do as much mappings as possible,
but if you do not know the right answer, do not map! Do not guess!

Decide each attribute in three steps:

1. The object. An attribute of a part is measured on the cad_object that IS
   that part: match the part's name and type against the cad_object reference
   (file name and #node) as well as its name. An exporter's generic name --
   "COMPOUND", "Open CASCADE STEP translator ..." -- says nothing; the file
   name then decides. A part marked "inside X" is a component of X. A cad_object that "contains" others
   is an assembly, and stands only for a part that is itself the assembly.
   Never measure a component on the assembly around it, even where the numbers
   would agree -- that is a plausible number from the wrong object.
2. The method. First: if the object lists a parameter whose name states
   exactly this attribute of this part (HOUSING_LENGTH_MM for housing.length,
   Params.Length for a box's length) and whose unit has the attribute's
   dimension, use method parameter with parameter_name set to that name,
   verbatim -- the stated dimension beats a measured approximation. Never a
   parameter whose name says another part or feature. Otherwise by the
   attribute's dimension: [length] -> bbox_size, [mass] -> mass,
   [length] ** 3 -> volume, dimensionless -> face_count. A [length] whose name
   ends in "radius" -> cylinder_radius, never bbox_size; set kind "hole" when
   the name says bore or hole. Use only a method the object lists as
   measurable.
3. The axis, for bbox_size: look up the attribute's name in the "axes" line.
   CAD systems differ, so never assume X, Y, Z. A name that is not in that
   line gets no bbox_size candidate.

Return one candidate for every attribute that passes all three steps, and
nothing for an attribute no listed measurement can express: a radius or a bore
is not a bounding-box extent, and a parameter answers only for the attribute
its name states.

Only name a sysml_part, attribute and cad_object that appear verbatim in the
excerpt; never invent, complete or correct a name. Never supply a density:
`mass` is listed only where the object's material is known.

Confidence: about 0.9 when name, type and a matching parameter agree, about
0.7 on the name alone. Rationale: one sentence naming that evidence, and say
when an extent is a bounding box rather than a named feature dimension.\
"""

INSTRUCTION = (
    "Return one candidate per attribute that passes the three steps, and none "
    "for the others. Use only names that appear above."
)


def _schema():
    from pydantic import BaseModel, Field

    class AiCandidate(BaseModel):
        sysml_part: str = Field(description="part name, verbatim from the excerpt")
        attribute: str = Field(description="attribute name, verbatim from the excerpt")
        cad_object: str = Field(description="cad_object reference, verbatim from the excerpt")
        method: Literal["bbox_size", "volume", "mass", "face_count", "cylinder_radius", "parameter"]
        axis: Literal["X", "Y", "Z"] | None = Field(default=None, description="required for bbox_size, omit otherwise")
        kind: Literal["hole", "boss"] | None = Field(default=None, description="cylinder_radius only: hole for a bore")
        parameter_name: str | None = Field(default=None, description="parameter only: the parameter's name, verbatim")
        # No density field, on purpose: a density is a fact about the part, and a
        # mapping entry carrying one goes stale when the material changes.
        confidence: float = Field(ge=0.0, le=1.0)
        rationale: str = Field(description="one sentence naming the actual evidence")

    class ProposalSet(BaseModel):
        candidates: list[AiCandidate]

    return ProposalSet


def json_schema():
    """The schema in the strict dialect: additionalProperties false, every property required."""
    return _strictify(_schema().model_json_schema())


def _strictify(node):
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _strictify(value) for key, value in node.items() if key != "default"}
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


def render_catalog(catalog):
    """The structural excerpt of both models, as text. Deterministic: same catalogue,
    same bytes -- which makes the prompt digest meaningful as provenance.

    Three things in it answer failures measured on real models: which part is nested
    in which ("inside gearbox"), which CAD object is an assembly of which others
    ("contains"), and which axis carries which named dimension.
    """
    lines = ["# SYSTEM MODEL", ""]
    used = set()
    for part in catalog.parts:
        where = "   (inside %s)" % part.container if part.container else ""
        lines.append("part %s : %s%s" % (part.name, part.definition or "?", where))
        for attribute in part.attributes:
            dimension = attribute.dimensionality
            spoken = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", attribute.name).lower().split()
            used.update(spoken[-1:])
            lines.append("    attribute %s : %s  [dimension: %s]"
                         % (attribute.name, attribute.type_name or "unknown",
                            dimension if dimension else "unknown to this tool"))
        lines.append("")

    lines += ["# CAD MODEL", ""]
    shown = [n for n in catalog.axes if n in ("length", "width", "height") or n in used]
    lines.append("axes for bbox_size: " + ", ".join("%s %s" % (n, catalog.axes[n]) for n in shown))
    lines.append("")

    references = {target.reference: target for target in catalog.targets}
    for target in catalog.targets:
        if not target.addressable:
            lines.append("cad_object %s  -- NOT ADDRESSABLE: %s" % (target.reference, target.note))
            continue
        lines.append("cad_object %s" % target.reference)
        lines.append("    name %s   kind %s   %s" % (target.name, target.kind, target.note))
        members = [t.reference for t in catalog.targets if _container(t) == target.reference]
        if members:
            lines.append("    contains: %s -- this is their assembly" % ", ".join(members))
        lines.append("    measurable: %s" % (", ".join(target.methods) or "nothing"))
        parent = references.get(_container(target))
        if parent is not None and parent is not target and parent.parameters == target.parameters:
            if target.parameters:
                lines.append("    parameters: those of %s, listed there" % parent.reference)
        else:
            for name, value in sorted(target.parameters.items()):
                lines.append("    parameter %s = %s" % (name, format(value, "~P")))
        lines.append("")
    return "\n".join(lines)


def _container(target):
    if target.container:
        return target.container
    return target.reference.split("#", 1)[0] if "#" in target.reference else ""


def prompt_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class LlmProposer:
    """Everything about asking a language model that does not depend on which one.
    A backend supplies ``_ask``; the excerpt, provenance and verification live here
    so a second backend cannot quietly do them differently."""

    provider = "llm"

    def __init__(self, model="", recorded=None):
        """``recorded`` is a saved JSON answer: tests exercise every line of _verify
        without a network or a key."""
        self.model = model
        self._recorded = recorded
        self.dropped = []

    @property
    def name(self):
        return "ai:%s" % self.model

    async def _ask(self, excerpt):
        """-> (parsed candidate set, response id)."""
        raise NotImplementedError

    def _replay(self):
        if self._recorded is None:
            return None
        return json.loads(self._recorded), "recorded"

    async def propose(self, catalog):
        self.dropped = []
        excerpt = render_catalog(catalog)
        digest = prompt_digest(SYSTEM + excerpt)
        parsed, response_id = await self._ask(excerpt)
        provenance = {"provider": self.provider, "model": self.model,
                      "prompt_digest": digest, "response_id": response_id}
        out = []
        for candidate in (parsed or {}).get("candidates", []):
            proposal = self._verify(candidate, catalog, provenance)
            if proposal is not None:
                out.append(proposal)
        return sorted(out, key=lambda p: p.confidence, reverse=True)

    def _verify(self, candidate, catalog, provenance):
        """Everything the schema cannot enforce: a schema guarantees the shape of an
        answer, not its truth. Every rejection is recorded, not dropped silently."""
        if not isinstance(candidate, dict):
            self.dropped.append("a candidate that is not an object: %r" % str(candidate)[:80])
            return None
        label = "%s.%s" % (candidate.get("sysml_part"), candidate.get("attribute"))

        try:
            confidence = float(candidate.get("confidence"))
        except (TypeError, ValueError):
            confidence = float("nan")
        if not 0.0 <= confidence <= 1.0:            # False for NaN as well
            self.dropped.append("%s: confidence %r is not a number in [0, 1]" % (label, candidate.get("confidence")))
            return None
        if candidate.get("density_g_per_cm3") is not None:
            self.dropped.append("%s: supplies a density -- a fact about the part, which no mapping entry "
                                "may carry" % label)
            return None

        part = catalog.part(candidate.get("sysml_part", ""))
        if part is None:
            self.dropped.append("no such part in the model: %r" % candidate.get("sysml_part"))
            return None
        attribute = catalog.attribute(part.name, candidate.get("attribute", ""))
        if attribute is None:
            self.dropped.append("%s has no attribute %r" % (part.name, candidate.get("attribute")))
            return None
        target = catalog.target(candidate.get("cad_object", ""))
        if target is None:
            self.dropped.append("no such CAD object: %r" % candidate.get("cad_object"))
            return None
        if not target.addressable:
            self.dropped.append("%s cannot be addressed: %s" % (target.reference, target.note))
            return None
        method = candidate.get("method", "")
        if method not in target.methods:
            self.dropped.append("%s does not offer %r (only %s)"
                                % (target.reference, method, ", ".join(target.methods) or "nothing"))
            return None

        args = {}
        if method == "bbox_size":
            axis = candidate.get("axis")
            if axis not in ("X", "Y", "Z"):
                self.dropped.append("%s.%s: bbox_size without an axis" % (part.name, attribute.name))
                return None
            args = {"axis": axis}
        elif method == "cylinder_radius":
            kind = candidate.get("kind")
            if kind not in (None, "hole", "boss"):
                self.dropped.append("%s.%s: cylinder_radius kind %r" % (part.name, attribute.name, kind))
                return None
            if kind is not None:
                args = {"kind": kind}
        elif method == "parameter":
            name = candidate.get("parameter_name")
            if not isinstance(name, str) or name not in target.parameters:
                self.dropped.append("%s.%s: %s has no parameter %r"
                                    % (part.name, attribute.name, target.reference, name))
                return None
            args = {"name": name}

        return Proposal(id="", sysml_part=part.name, attribute=attribute.name, adapter=target.adapter,
                        cad_object=target.reference, method=method, args=args, confidence=confidence,
                        rationale=str(candidate.get("rationale", "")).strip(), proposed_by=self.name,
                        provenance=provenance)


def parse_answer(content):
    """The first complete JSON value in a model's answer, a bare list taken as the
    candidate list.

    Ollama Cloud does not enforce ``format`` for every model: deepseek-v4.1-flash
    answers with the object -- or just ``[]`` -- in a ```json fence followed by
    prose. Only a complete value is taken (raw_decode fails on a truncated one);
    _verify and the gates still check every field of it. Raises
    json.JSONDecodeError when there is none.
    """
    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
        if not starts:
            raise exc
        parsed = json.JSONDecoder().raw_decode(text, min(starts))[0]
    return {"candidates": parsed} if isinstance(parsed, list) else parsed


class OllamaProposer(LlmProposer):
    """The platform's LLM: ``ctx.ai`` (Ollama Cloud, model OLLAMA_MODEL_BDS), with the
    response schema passed as Ollama's ``format``."""

    provider = "ollama"

    def __init__(self, ai, recorded=None):
        super().__init__(model=ai.model or "", recorded=recorded)
        self._ai = ai

    async def _ask(self, excerpt):
        replayed = self._replay()
        if replayed is not None:
            return replayed
        llm = self._ai.chat_model(format=json_schema(), temperature=0)
        response = await llm.ainvoke([("system", SYSTEM), ("human", "%s\n\n%s" % (excerpt, INSTRUCTION))])
        response_id = (getattr(response, "response_metadata", None) or {}).get("created_at", "")
        content = response.content if isinstance(response.content, str) else ""
        try:
            parsed = parse_answer(content)
        except json.JSONDecodeError as exc:
            # Nothing is salvaged from a partial body -- half a candidate list is
            # exactly the plausible-looking wrong answer this module refuses.
            self.dropped.append("the model did not return valid JSON (%s): %r" % (exc, content[:120]))
            return {"candidates": []}, response_id
        if not isinstance(parsed, dict) or not isinstance(parsed.get("candidates"), list):
            self.dropped.append("the model returned JSON without a `candidates` list")
            return {"candidates": []}, response_id
        return parsed, response_id
