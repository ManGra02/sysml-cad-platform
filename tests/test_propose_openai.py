"""The OpenAI-compatible backend's own half: the call, and what it does with
answers that are not what was asked for.

`test_propose_ai.py` already runs every verification test against this backend
through the recorded path. What is left here is the ~40 lines it actually owns
-- turning a chat completion into the candidate dict, and refusing to salvage
anything from a response that is not one.

A stub client stands in for the SDK. That is not a shortcut around a live test:
the cases worth pinning are a refusal, a truncated body and a server whose JSON
mode is advisory, and none of those can be summoned on demand from a real
endpoint. They can all be handed over by a stub.
"""

import json
import sys

import pytest

from sysmlcad.adapters import CadTarget
from sysmlcad.catalog import Catalog, CatalogAttribute, CatalogPart
from sysmlcad.propose_openai import (
    FORMAT_ENV,
    KEY_FILE_ENV,
    MODEL_ENV,
    OpenAIProposer,
    read_key_file,
)
from sysmlcad.units import ureg

PART = CatalogPart(
    name="motorHousing", element_id="p1", definition="Housing",
    attributes=(CatalogAttribute("length", "a1", "LengthValue"),),
)
SCRIPT = CadTarget(
    adapter="build123d", reference="motor_housing", kind="module",
    name="motor_housing", parameters={"LENGTH_MM": 118.0 * ureg.mm},
    note="material AlSi10Mg",
)
CATALOG = Catalog(parts=(PART,), targets=(SCRIPT,), source="test")

GOOD = {
    "candidates": [{
        "sysml_part": "motorHousing", "attribute": "length",
        "cad_object": "motor_housing", "method": "bbox_size", "axis": "X",
        "density_g_per_cm3": None, "confidence": 0.9,
        "rationale": "LENGTH_MM names the same quantity on the same object.",
    }]
}


class _Message:
    def __init__(self, content=None, refusal=None):
        self.content = content
        self.refusal = refusal


class _Response:
    """The shape the SDK returns, reduced to what `_ask` actually reads."""

    def __init__(self, content=None, refusal=None, response_id="resp-1"):
        self.choices = [type("Choice", (), {"message": _Message(content, refusal)})()]
        self.id = response_id


class _StubClient:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []
        completions = type("Completions", (), {"create": self._create})()
        self.chat = type("Chat", (), {"completions": completions})()

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _proposer(response):
    return OpenAIProposer(model="test-model", client=_StubClient(response))


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------

def test_a_well_formed_answer_becomes_a_proposal():
    proposer = _proposer(_Response(content=json.dumps(GOOD)))
    proposals = proposer.propose(CATALOG)

    assert len(proposals) == 1
    assert proposals[0].cad_object == "motor_housing"
    assert proposals[0].args == {"axis": "X"}
    assert proposals[0].proposed_by == "ai:test-model"
    assert proposals[0].provenance["provider"] == "openai-compatible"


def test_the_request_carries_the_schema_and_both_prompt_halves():
    proposer = _proposer(_Response(content=json.dumps(GOOD)))
    proposer.propose(CATALOG)
    sent = proposer._client.calls[0]

    assert sent["model"] == "test-model"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["messages"][0]["role"] == "system"
    assert "propose; a human confirms" in sent["messages"][0]["content"]
    assert "cad_object motor_housing" in sent["messages"][1]["content"]


def test_no_token_cap_is_sent():
    """`max_tokens` and `max_completion_tokens` are accepted by different
    servers and different model generations; sending the wrong one is a hard
    error, and the schema already bounds the answer."""
    proposer = _proposer(_Response(content=json.dumps(GOOD)))
    proposer.propose(CATALOG)
    sent = proposer._client.calls[0]

    assert "max_tokens" not in sent
    assert "max_completion_tokens" not in sent


# --------------------------------------------------------------------------
# Answers that are not answers
# --------------------------------------------------------------------------

def test_a_refusal_is_recorded_not_raised():
    """One model declining is a fact about that run, not a broken pipeline."""
    proposer = _proposer(_Response(refusal="I can't help with that"))

    assert proposer.propose(CATALOG) == []
    assert any("declined" in reason for reason in proposer.dropped)


def test_a_truncated_body_yields_nothing_and_says_why():
    """Half a candidate list is exactly the plausible-looking wrong answer this
    project refuses -- nothing is salvaged from it."""
    proposer = _proposer(_Response(content='{"candidates": [{"sysml_part": "motor'))

    assert proposer.propose(CATALOG) == []
    assert any(FORMAT_ENV in reason for reason in proposer.dropped)


def test_json_without_a_candidate_list_is_dropped():
    """Servers with advisory JSON modes return well-formed JSON of the wrong
    shape. It is caught here rather than raising a KeyError three frames up."""
    proposer = _proposer(_Response(content='{"mappings": []}'))

    assert proposer.propose(CATALOG) == []
    assert any("candidates" in reason for reason in proposer.dropped)


def test_an_invented_object_is_still_dropped_by_the_shared_verification():
    """The backend does not get its own verification, and this is what that
    buys: a name the catalogue has never heard of dies here regardless of how
    confidently the model asserted it."""
    answer = {"candidates": [dict(GOOD["candidates"][0], cad_object="turbine.step#Rotor")]}
    proposer = _proposer(_Response(content=json.dumps(answer)))

    assert proposer.propose(CATALOG) == []
    assert any("no such CAD object" in reason for reason in proposer.dropped)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def test_a_weaker_server_can_fall_back_to_plain_json_mode(monkeypatch):
    """Not every server that speaks the protocol supports strict schemas. The
    fallback weakens the guarantee about the answer's shape and changes nothing
    about what happens to its content."""
    monkeypatch.setenv(FORMAT_ENV, "json_object")
    proposer = _proposer(_Response(content=json.dumps(GOOD)))
    proposer.propose(CATALOG)
    sent = proposer._client.calls[0]

    assert sent["response_format"] == {"type": "json_object"}
    assert "Return JSON matching this schema exactly" in sent["messages"][1]["content"]
    assert '"additionalProperties": false' in sent["messages"][1]["content"]


def test_the_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv(MODEL_ENV, "qwen2.5-coder:32b")
    assert OpenAIProposer(client=object()).model == "qwen2.5-coder:32b"


def test_an_explicit_model_beats_the_environment(monkeypatch):
    monkeypatch.setenv(MODEL_ENV, "from-env")
    assert OpenAIProposer(model="explicit", client=object()).model == "explicit"


def test_no_client_is_built_while_replaying(monkeypatch):
    """The property that keeps CI free: the SDK is never imported, so a machine
    without it still runs every test above."""
    monkeypatch.delenv(MODEL_ENV, raising=False)
    proposer = OpenAIProposer(recorded=json.dumps(GOOD))

    assert proposer.propose(CATALOG)
    assert proposer._client is None


def test_a_missing_model_names_the_variable_to_set(monkeypatch):
    monkeypatch.delenv(MODEL_ENV, raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        OpenAIProposer()

    assert MODEL_ENV in str(excinfo.value)
    assert "no default" in str(excinfo.value)


# --------------------------------------------------------------------------
# The key file
# --------------------------------------------------------------------------

def test_the_trailing_newline_is_stripped(tmp_path):
    """The one that costs an hour when it is missing.

    Every editor ends a file with a newline. A trailing "\\n" in an
    Authorization header comes back as a 401, which reads exactly like a wrong
    key -- so the search starts at the key and never reaches the whitespace.
    """
    key_file = tmp_path / "apikey.txt"
    key_file.write_text("sk-example-value\n", encoding="utf-8")

    assert read_key_file(key_file) == "sk-example-value"


def test_only_the_first_line_is_used(tmp_path):
    """A key file often grows a comment or a second environment's key below."""
    key_file = tmp_path / "apikey.txt"
    key_file.write_text("sk-first\nsk-second\n", encoding="utf-8")

    assert read_key_file(key_file) == "sk-first"


def test_a_missing_key_file_says_where_it_looked(tmp_path):
    with pytest.raises(RuntimeError, match="no API key file at"):
        read_key_file(tmp_path / "absent.txt")


def test_an_empty_key_file_is_refused(tmp_path):
    """Better than handing an empty string to the SDK and reading its 401."""
    key_file = tmp_path / "apikey.txt"
    key_file.write_text("\n\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="no key on its first line"):
        read_key_file(key_file)


def test_the_key_file_wins_over_the_environment(tmp_path, monkeypatch):
    """Naming a file is the more specific instruction, and it is the
    arrangement that keeps the key out of the repository. A stale
    OPENAI_API_KEY left in a shell must not silently take precedence."""
    key_file = tmp_path / "apikey.txt"
    key_file.write_text("from-the-file\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from-the-environment")
    monkeypatch.setenv(KEY_FILE_ENV, str(key_file))

    captured = {}

    class _SDK:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", type("M", (), {"OpenAI": _SDK}))
    OpenAIProposer(model="test-model").client()

    assert captured["api_key"] == "from-the-file"


def test_a_key_never_reaches_a_log_line(tmp_path, monkeypatch):
    """Nothing this module prints may carry the key -- not an error message, not
    a dropped-candidate reason. A secret in a CI log is a leaked secret."""
    key_file = tmp_path / "apikey.txt"
    key_file.write_text("sk-secret-value\n", encoding="utf-8")
    monkeypatch.setenv(KEY_FILE_ENV, str(key_file))

    proposer = _proposer(_Response(content='{"nope": 1}'))
    proposer.propose(CATALOG)

    assert not any("sk-secret-value" in reason for reason in proposer.dropped)


# --------------------------------------------------------------------------
# Outages
# --------------------------------------------------------------------------

class _FailingClient(_StubClient):
    def __init__(self, error):
        super().__init__(response=None)
        self._error = error

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        raise self._error


def _api_error(cls):
    """Build an SDK error without a real HTTP round trip."""
    import httpx2 as httpx
    request = httpx.Request("POST", "https://example.invalid/chat/completions")
    response = httpx.Response(503, request=request, json={"error": {"message": "busy"}})
    return cls("high demand", response=response, body=None)


def test_a_busy_server_is_reported_not_raised():
    """A 503 is a fact about this run, not a broken pipeline. Crashing would
    also discard the baseline's score, computed just before this call, which is
    the number the model exists to be compared against."""
    from openai import InternalServerError

    proposer = OpenAIProposer(model="test-model", client=_FailingClient(_api_error(InternalServerError)))

    assert proposer.propose(CATALOG) == []
    assert any("could not be reached" in reason for reason in proposer.dropped)


def test_a_rate_limit_is_reported_not_raised():
    from openai import RateLimitError

    proposer = OpenAIProposer(model="test-model", client=_FailingClient(_api_error(RateLimitError)))

    assert proposer.propose(CATALOG) == []
    assert proposer.dropped


def test_a_wrong_key_or_model_still_raises():
    """The opposite case, and the reason the transient list is explicit: a 401
    or a 404 is the caller's to fix. Swallowed, it would read as "the model
    proposed nothing" and send the search in exactly the wrong direction."""
    from openai import NotFoundError

    proposer = OpenAIProposer(model="typo-model", client=_FailingClient(_api_error(NotFoundError)))

    with pytest.raises(NotFoundError):
        proposer.propose(CATALOG)
