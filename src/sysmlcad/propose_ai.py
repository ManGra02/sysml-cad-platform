"""LLM proposers: a language model suggests mappings, and nothing else.

SRS FREQ-4: "the system passes a structural excerpt of both models to the AI
service, which returns candidate correspondences [...] Each candidate carries a
confidence value and a short rationale. Candidates are never applied
automatically; they enter the mapping table with the status proposed."

That is the whole job. This module is a `Proposer` like `DifflibProposer` is a
`Proposer`: same input, same output type, same gates, same scoreboard. Once a
candidate is confirmed, nothing anywhere behaves differently because a language
model suggested it -- which is exactly what NFREQ-1 asks for and what makes an
AI safe to have here at all.

FOUR THINGS THAT KEEP IT HONEST
-------------------------------
1. **Structured output, not prose.** The server validates the response
   against a strict JSON schema, so a malformed answer is a validation error rather than a
   plausible-looking wrong mapping.
2. **Every field is checked against the catalogue.** A model that names a CAD
   object which does not exist, or an attribute the part does not have, gets
   dropped with the reason recorded. This is the failure mode to expect, and
   the schema alone does not prevent it.
3. **Then the ordinary gates.** Dimension, existence, uniqueness, plausibility,
   exactly as for the baseline -- `propose.run()` applies them to whatever a
   proposer returns.
4. **Provenance on every candidate.** Model id, a digest of the prompt, and the
   response id, stored with the proposal. A suggestion nobody can trace back to
   the thing that made it is not evidence of anything.

Those four hold for *any* model, which is why they live in `LlmProposer` and a
backend only implements `_ask`. The one backend, in `propose_openai.py`, is
OpenAI-compatible and so reaches OpenAI, Azure, vLLM, Ollama, LM Studio, the
UPB gateway, Google AI Studio and anything else speaking that protocol. Swapping the model changes the
scoreboard, never the safety properties.

CI never calls any of them. The tests drive them with a recorded response, and
`requirements.txt` carries no SDK -- installing one is a deliberate step for
whoever wants the AI path.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from .catalog import Catalog, load_catalog
from .proposals import Proposal

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
2. The method, by the attribute's dimension: [length] -> bbox_size,
   [mass] -> mass, [length] ** 3 -> volume, dimensionless -> face_count. A
   [length] whose name ends in "radius" -> cylinder_radius, never bbox_size;
   set kind "hole" when the name says bore or hole. Use only a method the
   object lists as measurable.
3. The axis, for bbox_size: look up the attribute's name in the "axes" line.
   CAD systems differ, so never assume X, Y, Z. A name that is not in that
   line gets no bbox_size candidate.

Return one candidate for every attribute that passes all three steps, and
nothing for an attribute no listed measurement can express: a radius or a bore
is not a bounding-box extent, and a named parameter is evidence, not a
measurement -- no method reads it.

Only name a sysml_part, attribute and cad_object that appear verbatim in the
excerpt; never invent, complete or correct a name. Never supply a density:
`mass` is listed only where the object's material is known.

Confidence: about 0.9 when name, type and a matching parameter agree, about
0.7 on the name alone. Rationale: one sentence naming that evidence, and say
when an extent is a bounding box rather than a named feature dimension.\
"""

#: The closing instruction, after the excerpt. One constant for every backend,
#: so the part of the prompt that varies between runs is the excerpt alone.
INSTRUCTION = (
    "Return one candidate per attribute that passes the three steps, and none "
    "for the others. Use only names that appear above."
)


# --------------------------------------------------------------------------
# The response schema
# --------------------------------------------------------------------------

def _schema():
    """Built lazily: pydantic arrives with the SDK, which is an optional extra."""
    from pydantic import BaseModel, Field

    class AiCandidate(BaseModel):
        sysml_part: str = Field(description="part name, verbatim from the excerpt")
        attribute: str = Field(description="attribute name, verbatim from the excerpt")
        cad_object: str = Field(description="cad_object reference, verbatim from the excerpt")
        method: Literal["bbox_size", "volume", "mass", "face_count", "cylinder_radius"]
        axis: Literal["X", "Y", "Z"] | None = Field(
            default=None, description="required for bbox_size, omit otherwise"
        )
        kind: Literal["hole", "boss"] | None = Field(
            default=None, description="cylinder_radius only: hole for a bore"
        )
        # No density field, on purpose. A density is a fact about the part, and
        # a mapping entry carrying one goes silently stale when the material
        # changes -- see `test_the_committed_mapping_carries_no_density`.
        confidence: float = Field(ge=0.0, le=1.0)
        rationale: str = Field(description="one sentence naming the actual evidence")

    class ProposalSet(BaseModel):
        candidates: list[AiCandidate]

    return ProposalSet


def json_schema() -> dict:
    """The same schema as plain JSON Schema, in the strict dialect.

    An OpenAI-compatible server wants JSON Schema with `additionalProperties: false` and every
    property listed in `required`. Deriving it from the one pydantic model keeps
    a single definition -- two hand-written schemas would drift, and the drift
    would show up as a model that suddenly cannot answer.
    """
    return _strictify(_schema().model_json_schema())


def _strictify(node):
    """Recursively make a pydantic-generated schema strict-mode acceptable."""
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node

    out = {key: _strictify(value) for key, value in node.items() if key != "default"}
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        # Strict mode has no notion of an optional property: a field that may be
        # absent is expressed as a nullable type instead, which pydantic has
        # already done for `axis`, `kind` and `density_g_per_cm3`.
        out["required"] = list(out["properties"])
    return out


# --------------------------------------------------------------------------
# The excerpt
# --------------------------------------------------------------------------

def render_catalog(catalog: Catalog) -> str:
    """The structural excerpt of both models, as text.

    Deterministic on purpose: same catalogue, same bytes. That makes the prompt
    digest meaningful as provenance and lets the prefix be cached across runs.

    Three things in it answer failures measured on real models: which part is
    nested in which ("inside gearbox"), which CAD object is an assembly of
    which others ("contains"), and which axis carries which named dimension.
    A component's parameters are the module's and are listed once, on the
    module -- repeated under every component they read as that component's.
    """
    lines = ["# SYSTEM MODEL", ""]
    used: set[str] = set()
    for part in catalog.parts:
        where = f"   (inside {part.container})" if part.container else ""
        lines.append(f"part {part.name} : {part.definition or '?'}{where}")
        for attribute in part.attributes:
            dimension = attribute.dimensionality
            words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", attribute.name).lower().split()
            used.update(words[-1:])
            lines.append(
                f"    attribute {attribute.name} : {attribute.type_name or 'unknown'}"
                f"  [dimension: {dimension if dimension else 'unknown to this tool'}]"
            )
        lines.append("")

    lines += ["# CAD MODEL", ""]
    # How this CAD side is oriented, for the names this model uses. Without it
    # a model can only guess which axis a "length" lies along -- and a CAD
    # system that puts it on Y would have every such guess wrong in the same,
    # plausible-looking way.
    shown = [n for n in catalog.axes if n in ("length", "width", "height") or n in used]
    lines.append(
        "axes for bbox_size: " + ", ".join(f"{n} {catalog.axes[n]}" for n in shown)
    )
    lines.append("")

    references = {target.reference: target for target in catalog.targets}
    for target in catalog.targets:
        if not target.addressable:
            lines.append(f"cad_object {target.reference}  -- NOT ADDRESSABLE: {target.note}")
            continue
        lines.append(f"cad_object {target.reference}")
        lines.append(f"    name {target.name}   kind {target.kind}   {target.note}")
        members = [r for r in references if r.startswith(target.reference + "#")]
        if members:
            lines.append(f"    contains: {', '.join(members)} -- this is their assembly")
        lines.append(f"    measurable: {', '.join(target.methods) or 'nothing'}")
        parent = references.get(target.reference.split("#", 1)[0])
        if parent is not None and parent is not target and parent.parameters == target.parameters:
            if target.parameters:
                lines.append(f"    parameters: those of {parent.reference}, listed there")
        else:
            for name, value in sorted(target.parameters.items()):
                lines.append(f"    parameter {name} = {value:~P}")
        lines.append("")

    return "\n".join(lines)


def prompt_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# The proposer
# --------------------------------------------------------------------------

class LlmProposer:
    """Everything about asking a language model that does not depend on which one.

    A backend supplies `_ask`; this class supplies the parts that keep the
    answer honest -- the excerpt, the provenance, and the verification against
    the catalogue. That split is deliberate: those checks are the reason a model
    can be swapped at all, so they must not live in a backend where a second
    implementation could quietly do them differently.

    Subclasses set `provider` and `default_model` (empty means the backend
    names its model some other way, as `propose_openai` does from the
    environment).
    """

    provider: str = "llm"
    default_model: str = ""

    def __init__(
        self,
        model: str | None = None,
        client=None,
        recorded: str | None = None,
    ):
        """`recorded` is a saved JSON response, so tests and CI exercise every
        line of the validation below without a network or a key."""
        self.model = model or self.default_model
        self._client = client
        self._recorded = recorded
        self.dropped: list[str] = []

    @property
    def name(self) -> str:
        return f"ai:{self.model}"

    def client(self):  # pragma: no cover - overridden by every backend
        raise NotImplementedError

    def _ask(self, excerpt: str) -> tuple[dict, str]:
        """Ask the model. Returns the parsed candidate set and a response id.

        The only method a new backend has to write. It must return the shape
        `_schema()` describes; anything else is caught by `_verify`, which is
        where a backend's mistakes and a model's mistakes are treated alike.
        """
        raise NotImplementedError

    def _replay(self) -> tuple[dict, str] | None:
        """The recorded path, shared so every backend is testable the same way."""
        if self._recorded is None:
            return None
        return json.loads(self._recorded), "recorded"

    # -- Proposer ----------------------------------------------------------

    def propose(self, catalog: Catalog) -> list[Proposal]:
        self.dropped = []
        excerpt = render_catalog(catalog)
        digest = prompt_digest(SYSTEM + excerpt)
        parsed, response_id = self._ask(excerpt)

        provenance = {
            "provider": self.provider,
            "model": self.model,
            "prompt_digest": digest,
            "response_id": response_id,
        }

        out: list[Proposal] = []
        for candidate in parsed.get("candidates", []):
            proposal = self._verify(candidate, catalog, provenance)
            if proposal is not None:
                out.append(proposal)
        return sorted(out, key=lambda p: p.confidence, reverse=True)

    def _verify(self, candidate: dict, catalog: Catalog, provenance: dict) -> Proposal | None:
        """Everything the schema cannot enforce.

        A schema guarantees the shape of an answer, not its truth: a model can
        return a perfectly typed `cad_object` that does not exist. Each check
        below is a way a confident answer can still be fiction, and every
        rejection is recorded rather than dropped silently -- a proposer that
        invents names systematically is worth knowing about.

        Not even the shape is guaranteed on a server running in plain JSON mode
        (`SYSMLCAD_OPENAI_RESPONSE_FORMAT=json_object`), so the types are
        checked here too: a candidate that is not an object, or whose
        confidence is not a number in [0, 1], is dropped rather than crashing
        the run or ranking a proposal by a meaningless score.
        """
        if not isinstance(candidate, dict):
            self.dropped.append(f"a candidate that is not an object: {str(candidate)[:80]!r}")
            return None

        try:
            confidence = float(candidate.get("confidence"))
        except (TypeError, ValueError):
            confidence = float("nan")
        if not 0.0 <= confidence <= 1.0:          # False for NaN as well
            self.dropped.append(
                f"{candidate.get('sysml_part')}.{candidate.get('attribute')}: "
                f"confidence {candidate.get('confidence')!r} is not a number in [0, 1]"
            )
            return None

        if candidate.get("density_g_per_cm3") is not None:
            # The schema has no such field; a server that does not enforce it
            # can still send one. A density in the mapping overrides the
            # material the CAD side declares and goes stale when it changes.
            self.dropped.append(
                f"{candidate.get('sysml_part')}.{candidate.get('attribute')}: "
                f"supplies a density ({candidate['density_g_per_cm3']!r}) -- a fact "
                f"about the part, which no mapping entry may carry"
            )
            return None

        part = catalog.part(candidate.get("sysml_part", ""))
        if part is None:
            self.dropped.append(f"no such part in the model: {candidate.get('sysml_part')!r}")
            return None

        attribute = catalog.attribute(part.name, candidate.get("attribute", ""))
        if attribute is None:
            self.dropped.append(
                f"{part.name} has no attribute {candidate.get('attribute')!r}"
            )
            return None

        target = catalog.target(candidate.get("cad_object", ""))
        if target is None:
            self.dropped.append(f"no such CAD object: {candidate.get('cad_object')!r}")
            return None
        if not target.addressable:
            self.dropped.append(f"{target.reference} cannot be addressed: {target.note}")
            return None

        method = candidate.get("method", "")
        if method not in target.methods:
            self.dropped.append(
                f"{target.reference} does not offer {method!r} "
                f"(only {', '.join(target.methods) or 'nothing'})"
            )
            return None

        args: dict = {}
        if method == "bbox_size":
            axis = candidate.get("axis")
            if axis not in ("X", "Y", "Z"):
                self.dropped.append(
                    f"{part.name}.{attribute.name}: bbox_size without an axis"
                )
                return None
            args = {"axis": axis}
        elif method == "cylinder_radius":
            kind = candidate.get("kind")
            if kind not in (None, "hole", "boss"):
                self.dropped.append(
                    f"{part.name}.{attribute.name}: cylinder_radius kind {kind!r}"
                )
                return None
            if kind is not None:
                args = {"kind": kind}

        return Proposal(
            id="",
            sysml_part=part.name,
            attribute=attribute.name,
            adapter=target.adapter,
            cad_object=target.reference,
            method=method,
            args=args,
            confidence=confidence,
            rationale=str(candidate.get("rationale", "")).strip(),
            proposed_by=self.name,
            provenance=provenance,
        )
