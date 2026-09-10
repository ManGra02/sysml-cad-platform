"""A proposer for any server that speaks the OpenAI chat protocol.

One backend, many models: OpenAI itself, Azure OpenAI, vLLM, LM Studio, Groq,
OpenRouter, together.ai, and Ollama through its OpenAI-compatible endpoint. The
protocol is the interface, so switching between them is a change of environment
rather than a change of code.

    export OPENAI_BASE_URL=http://localhost:11434/v1   # Ollama, say
    export OPENAI_API_KEY=whatever                     # local servers ignore it
    export SYSMLCAD_OPENAI_MODEL=qwen2.5-coder:32b
    make propose AI=openai
    make propose-score AI=openai

WHAT THIS MODULE IS, AND WHAT IT DELIBERATELY IS NOT
----------------------------------------------------
It is `_ask` and nothing else. The excerpt, the prompt, the schema, the
provenance and -- most importantly -- the verification of every candidate
against the catalogue all live in `LlmProposer`, shared with the Claude
backend. That is not tidiness: those checks are the reason an arbitrary model
can be pointed at this system at all, and a second copy of them here would be a
second chance to get them subtly wrong.

The practical consequence is worth stating plainly. A weaker or smaller model
does not become dangerous here, only less useful: whatever it returns is
checked field by field against the catalogue, then run through the same four
gates, then shown to a human. What changes with model quality is the
scoreboard, never the safety properties. `make propose-score AI=openai` is how
you find out which side of the 11/13 baseline your model falls on.

ONE PORTABILITY NOTE
--------------------
Strict `json_schema` response formats are supported by OpenAI, vLLM, LM Studio
and recent Ollama, but not by every server that claims the protocol. Where a
server rejects it, `SYSMLCAD_OPENAI_RESPONSE_FORMAT=json_object` falls back to
plain JSON mode and the schema goes into the prompt instead. That is a weaker
guarantee about the *shape* of the answer -- and no change at all to what
happens to its *content*, which was never trusted in the first place.
"""

from __future__ import annotations

import json
import os

from .propose_ai import SYSTEM, LlmProposer, json_schema

#: Read by the SDK itself; listed here because they are what a user actually
#: sets, and naming them in one place beats hunting through a traceback.
BASE_URL_ENV = "OPENAI_BASE_URL"
API_KEY_ENV = "OPENAI_API_KEY"

#: Ours: the protocol has no notion of a default model, and guessing one would
#: silently bill a model the user did not choose.
MODEL_ENV = "SYSMLCAD_OPENAI_MODEL"
FORMAT_ENV = "SYSMLCAD_OPENAI_RESPONSE_FORMAT"


class OpenAIProposer(LlmProposer):
    """Asks an OpenAI-protocol model for candidates, then verifies all of them."""

    provider = "openai-compatible"

    def __init__(self, model: str | None = None, client=None, recorded: str | None = None):
        super().__init__(model=model or os.environ.get(MODEL_ENV, ""), client=client,
                         recorded=recorded)
        if not self.model and recorded is None:
            raise RuntimeError(
                f"no model chosen. Set {MODEL_ENV} to the model this server "
                f"serves, e.g. `export {MODEL_ENV}=gpt-4o` or "
                f"`export {MODEL_ENV}=qwen2.5-coder:32b`. There is no default: "
                f"picking one for you would run a model you did not choose."
            )
        self.model = self.model or "recorded"

    # -- the client --------------------------------------------------------

    def client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on the env
                raise RuntimeError(
                    "the OpenAI-compatible proposer needs the SDK: pip install openai"
                ) from exc

            # Base URL and key resolve the SDK's own way. The one exception is a
            # local server: it ignores the key entirely, but the SDK refuses to
            # start without one, and telling somebody running Ollama to invent
            # an API key is a poor first experience.
            kwargs = {}
            if not os.environ.get(API_KEY_ENV) and os.environ.get(BASE_URL_ENV):
                kwargs["api_key"] = "not-required-by-this-server"
            self._client = OpenAI(**kwargs)
        return self._client

    # -- the call ----------------------------------------------------------

    def _response_format(self) -> tuple[dict, str]:
        """The response format, and whatever the prompt has to say about it."""
        if os.environ.get(FORMAT_ENV) == "json_object":
            schema = json.dumps(json_schema(), indent=2)
            return (
                {"type": "json_object"},
                f"\n\nReturn JSON matching this schema exactly:\n{schema}",
            )
        return (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "proposal_set",
                    "strict": True,
                    "schema": json_schema(),
                },
            },
            "",
        )

    def _ask(self, excerpt: str) -> tuple[dict, str]:
        replayed = self._replay()
        if replayed is not None:
            return replayed

        response_format, schema_note = self._response_format()

        # No token cap on purpose: `max_tokens` and `max_completion_tokens` are
        # accepted by different servers and different model generations, and
        # sending the wrong one is a hard error. The schema bounds the answer,
        # and a truncated body fails to parse rather than passing silently.
        response = self.client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"{excerpt}\n\n"
                        f"Propose the mappings you are confident about. Use only "
                        f"names that appear above.{schema_note}"
                    ),
                },
            ],
            response_format=response_format,
        )

        choice = response.choices[0]

        # Structured outputs can come back as an explicit refusal instead of
        # content. Recorded as a dropped candidate, not raised: one model
        # declining is a fact about that run, not a broken pipeline.
        refusal = getattr(choice.message, "refusal", None)
        if refusal:
            self.dropped.append(f"the model declined to answer ({refusal})")
            return {"candidates": []}, getattr(response, "id", "")

        content = choice.message.content or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            # Expected on servers whose JSON mode is advisory. Nothing is
            # salvaged from a partial body -- half a candidate list is exactly
            # the kind of plausible-looking wrong answer this project refuses.
            self.dropped.append(
                f"the model did not return valid JSON ({exc}); "
                f"if this server does not support strict schemas, try "
                f"{FORMAT_ENV}=json_object"
            )
            return {"candidates": []}, getattr(response, "id", "")

        if not isinstance(parsed, dict) or not isinstance(parsed.get("candidates"), list):
            self.dropped.append(
                "the model returned JSON without a `candidates` list "
                f"(top-level keys: {sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__})"
            )
            return {"candidates": []}, getattr(response, "id", "")

        return parsed, getattr(response, "id", "")


def main() -> int:  # pragma: no cover - needs a server
    """`python -m sysmlcad.propose_openai` -- the same flow as `propose`."""
    from .propose import main as propose_main

    return propose_main(["--ai", "openai"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
