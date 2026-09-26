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

A key in a file rather than the environment is often the safer arrangement --
it can live outside the repository, where no `git add -A` can reach it, and it
never shows up in a process listing or a shell history:

    export SYSMLCAD_OPENAI_API_KEY_FILE=/workspaces/conf/upb_ai_api_key.txt

The first line is used, stripped. That strip is load-bearing: every editor ends
a file with a newline, and a trailing "\n" in an Authorization header comes
back as a 401 that reads exactly like a wrong key.

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
you find out which side of the baseline your model falls on.

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
from pathlib import Path

from .propose_ai import INSTRUCTION, SYSTEM, LlmProposer, json_schema

#: Failures worth continuing past: the server was busy, slow or briefly gone.
#: A wrong key, a wrong model name or a malformed request is NOT in here on
#: purpose -- those are the caller's to fix, and swallowing them would show up
#: as "the model proposed nothing", sending the search in the wrong direction.
def _transient_errors():
    try:
        from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
    except ImportError:  # pragma: no cover - the SDK is an optional extra
        return ()
    return (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)

#: Read by the SDK itself; listed here because they are what a user actually
#: sets, and naming them in one place beats hunting through a traceback.
BASE_URL_ENV = "OPENAI_BASE_URL"
API_KEY_ENV = "OPENAI_API_KEY"

#: Ours: the protocol has no notion of a default model, and guessing one would
#: silently bill a model the user did not choose.
MODEL_ENV = "SYSMLCAD_OPENAI_MODEL"
FORMAT_ENV = "SYSMLCAD_OPENAI_RESPONSE_FORMAT"

#: A file holding the key, so it can live outside the repository. Preferred over
#: `OPENAI_API_KEY` when set: naming a file is a more specific instruction than
#: whatever happens to be in the environment.
KEY_FILE_ENV = "SYSMLCAD_OPENAI_API_KEY_FILE"


def read_key_file(path: str | Path) -> str:
    """The first line of a key file, stripped.

    The strip is not cosmetic. Editors end files with a newline, and a trailing
    "\n" in an Authorization header produces a 401 -- which reads exactly like
    a wrong key and sends you looking in the wrong place for an hour.
    """
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"no API key file at {path}")

    first = path.read_text(encoding="utf-8").splitlines()
    key = first[0].strip() if first else ""
    if not key:
        raise RuntimeError(f"{path} has no key on its first line")
    return key


_TRANSIENT = _transient_errors() or ()


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

            # Base URL and key resolve the SDK's own way, with two exceptions.
            # A key file wins when named: it is the more specific instruction,
            # and it is the arrangement that keeps the key out of the repository
            # and out of the environment. And a local server ignores the key
            # entirely while the SDK still refuses to start without one --
            # telling somebody running Ollama to invent an API key is a poor
            # first experience.
            kwargs = {}
            key_file = os.environ.get(KEY_FILE_ENV)
            if key_file:
                kwargs["api_key"] = read_key_file(key_file)
            elif not os.environ.get(API_KEY_ENV) and os.environ.get(BASE_URL_ENV):
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

    def _call(self, excerpt: str, response_format: dict, schema_note: str):
        """The request itself.

        No token cap on purpose: `max_tokens` and `max_completion_tokens` are
        accepted by different servers and different model generations, and
        sending the wrong one is a hard error. The schema bounds the answer, and
        a truncated body fails to parse rather than passing silently.
        """
        return self.client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": f"{excerpt}\n\n{INSTRUCTION}{schema_note}",
                },
            ],
            response_format=response_format,
        )

    def _ask(self, excerpt: str) -> tuple[dict, str]:
        replayed = self._replay()
        if replayed is not None:
            return replayed

        response_format, schema_note = self._response_format()

        try:
            response = self._call(excerpt, response_format, schema_note)
        except _TRANSIENT as exc:
            # An outage is a fact about this run, not a broken pipeline -- the
            # same treatment a refusal gets. Crashing here would also throw away
            # the baseline's result, which was computed before this call and is
            # the number the model was going to be compared against.
            self.dropped.append(
                f"the server could not be reached ({type(exc).__name__}: "
                f"{str(exc)[:120]}) -- no candidates from this run"
            )
            return {"candidates": []}, "unavailable"

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
