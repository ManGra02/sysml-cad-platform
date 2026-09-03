"""The AI proposer: Claude suggests mappings, and nothing else.

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
1. **Structured output, not prose.** `messages.parse` validates the response
   against a schema, so a malformed answer is a validation error rather than a
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

CI never calls this. The tests drive it with a recorded response, and
`requirements.txt` does not carry the SDK -- `pip install anthropic` is a
deliberate step for whoever wants the AI path.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from .catalog import Catalog, load_catalog
from .proposals import Proposal

MODEL = "claude-opus-5"

#: Keep well clear of the response cap: a truncated JSON body is a parse error,
#: and on a large catalogue the candidate list is the long part of the answer.
MAX_TOKENS = 16000

SYSTEM = """\
You map systems-engineering model attributes onto CAD measurements.

You are one half of a two-part process. You propose; a human confirms. Every
candidate you return is checked by machine afterwards -- dimensional
compatibility, whether the measurement is possible at all, uniqueness, order of
magnitude -- and then reviewed by an engineer. So a wrong suggestion is not
caught by you being confident; it is caught by those checks, and it costs a
person time either way.

Two rules that matter more than coverage:

* Only ever name a `sysml_part`, `attribute` and `cad_object` that appear
  verbatim in the excerpt. Never invent, complete or correct a name.
* If nothing in the CAD model plausibly corresponds to an attribute, return no
  candidate for it. A gap a human fills is cheaper than a wrong mapping a human
  has to detect. Low confidence is not a substitute for silence.

`bbox_size` measures the bounding box along one axis, which is not the same
thing as a named feature dimension -- say so in the rationale when you use it.
`mass` needs a density: the object's material if the excerpt lists one,
otherwise `density_g_per_cm3`.

Keep each rationale to one sentence naming the actual evidence -- the names that
matched, the parameter you relied on. "Seems related" is not a rationale.\
"""


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
        method: Literal["bbox_size", "volume", "mass", "face_count"]
        axis: Literal["X", "Y", "Z"] | None = Field(
            default=None, description="required for bbox_size, omit otherwise"
        )
        density_g_per_cm3: float | None = Field(
            default=None,
            description="only for mass on an object with no material listed",
        )
        confidence: float = Field(ge=0.0, le=1.0)
        rationale: str = Field(description="one sentence naming the actual evidence")

    class ProposalSet(BaseModel):
        candidates: list[AiCandidate]

    return ProposalSet


# --------------------------------------------------------------------------
# The excerpt
# --------------------------------------------------------------------------

def render_catalog(catalog: Catalog) -> str:
    """The structural excerpt of both models, as text.

    Deterministic on purpose: same catalogue, same bytes. That makes the prompt
    digest meaningful as provenance and lets the prefix be cached across runs.
    """
    lines = ["# SYSTEM MODEL", ""]
    for part in catalog.parts:
        lines.append(f"part {part.name} : {part.definition or '?'}")
        for attribute in part.attributes:
            dimension = attribute.dimensionality
            lines.append(
                f"    attribute {attribute.name} : {attribute.type_name or 'unknown'}"
                f"  [dimension: {dimension if dimension else 'unknown to this tool'}]"
            )
        lines.append("")

    lines += ["# CAD MODEL", ""]
    for target in catalog.targets:
        if not target.addressable:
            lines.append(f"cad_object {target.reference}  -- NOT ADDRESSABLE: {target.note}")
            continue
        lines.append(f"cad_object {target.reference}")
        lines.append(f"    name {target.name}   kind {target.kind}   {target.note}")
        lines.append(f"    measurable: {', '.join(target.methods) or 'nothing'}")
        for name, value in sorted(target.parameters.items()):
            lines.append(f"    parameter {name} = {value:~P}")
        lines.append("")

    return "\n".join(lines)


def prompt_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# The proposer
# --------------------------------------------------------------------------

class ClaudeProposer:
    """Asks Claude for candidates, then throws away everything it cannot verify."""

    def __init__(
        self,
        model: str = MODEL,
        client=None,
        recorded: str | None = None,
    ):
        """`recorded` is a saved JSON response, so tests and CI exercise every
        line of the validation below without a network or a key."""
        self.model = model
        self._client = client
        self._recorded = recorded
        self.dropped: list[str] = []

    @property
    def name(self) -> str:
        return f"ai:{self.model}"

    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on the env
                raise RuntimeError(
                    "the AI proposer needs the Anthropic SDK: pip install anthropic"
                ) from exc
            # Credentials resolve the SDK's own way -- ANTHROPIC_API_KEY, or a
            # profile from `ant auth login`. No bespoke key handling here.
            self._client = anthropic.Anthropic()
        return self._client

    # -- the call ----------------------------------------------------------

    def _ask(self, excerpt: str) -> tuple[dict, str]:
        """Returns the parsed response and its id."""
        if self._recorded is not None:
            return json.loads(self._recorded), "recorded"

        response = self.client().messages.parse(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM,
                # The system prompt and the excerpt are the stable prefix; only
                # the closing instruction varies between runs.
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": (
                    f"{excerpt}\n\n"
                    f"Propose the mappings you are confident about. Use only "
                    f"names that appear above."
                ),
            }],
            output_format=_schema(),
        )

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            self.dropped.append(
                f"the model declined to answer "
                f"({getattr(details, 'category', 'no category given')})"
            )
            return {"candidates": []}, getattr(response, "id", "")

        return response.parsed_output.model_dump(), getattr(response, "id", "")

    # -- Proposer ----------------------------------------------------------

    def propose(self, catalog: Catalog) -> list[Proposal]:
        self.dropped = []
        excerpt = render_catalog(catalog)
        digest = prompt_digest(SYSTEM + excerpt)
        parsed, response_id = self._ask(excerpt)

        provenance = {
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
        """
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
        elif method == "mass" and candidate.get("density_g_per_cm3") is not None:
            args = {"density_g_per_cm3": float(candidate["density_g_per_cm3"])}

        return Proposal(
            id="",
            sysml_part=part.name,
            attribute=attribute.name,
            adapter=target.adapter,
            cad_object=target.reference,
            method=method,
            args=args,
            confidence=float(candidate.get("confidence", 0.0)),
            rationale=str(candidate.get("rationale", "")).strip(),
            proposed_by=self.name,
            provenance=provenance,
        )


def main() -> int:  # pragma: no cover - needs credentials
    """`python -m sysmlcad.propose_ai` -- the same flow as `propose`, one model."""
    from .propose import main as propose_main

    return propose_main(["--ai"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
