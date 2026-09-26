"""The LLM proposers, driven by a recorded response.

No network, no API key, no cost -- and every line of the validation runs. That
is deliberate beyond convenience: the tests that matter here are about what
happens when the model is *wrong*, and a live call cannot be relied upon to be
wrong in the ways worth testing.

`fixtures/ai_response.json` is constructed rather than captured, which its own
`_comment` says. Its last four candidates are the four ways a perfectly
well-formed answer can still be fiction:

    invented CAD object   .  attribute the part does not have
    bbox_size with no axis  .  a measurement the target cannot make

A schema guarantees the shape of an answer, not its truth. These tests are what
stands between a confidently-typed hallucination and `mapping.yaml`.

EVERY VALIDATION TEST RUNS AGAINST EVERY BACKEND. That parametrisation is the
point of the shared `LlmProposer`, made checkable: a new backend inherits all of
these the moment it appears in `AI_PROPOSERS`, and if someone re-implements the
verification inside one of them, the suite says so. Which model answered is the
one thing that may differ between backends; what happens to the answer is not.
"""

import json
from pathlib import Path

import pytest

from sysmlcad.adapters import CadTarget
from sysmlcad.catalog import Catalog, CatalogAttribute, CatalogPart
from sysmlcad.propose import AI_PROPOSERS
from sysmlcad.propose_ai import ClaudeProposer, json_schema, prompt_digest, render_catalog
from sysmlcad.propose_openai import OpenAIProposer
from sysmlcad.units import ureg

RESPONSE = (Path(__file__).resolve().parents[1] / "fixtures" / "ai_response.json")

PART = CatalogPart(
    name="motorHousing", element_id="p1", definition="Housing",
    attributes=(
        CatalogAttribute("length", "a1", "LengthValue"),
        CatalogAttribute("mass", "a2", "MassValue"),
    ),
)
SCRIPT = CadTarget(
    adapter="build123d", reference="motor_housing", kind="module",
    name="motor_housing", parameters={"LENGTH_MM": 118.0 * ureg.mm},
    note="material AlSi10Mg",
)
STEP_NODE = CadTarget(
    adapter="step", reference="fixtures/step/gearbox.step#Housing", kind="part",
    name="Housing", methods=("bbox_size", "volume", "face_count"),
    note="no material in the file",
)
CATALOG = Catalog(parts=(PART,), targets=(SCRIPT, STEP_NODE), source="test")


#: Every backend, driven the same way. `recorded` short-circuits the network
#: call each one would otherwise make, leaving exactly the shared half under
#: test -- which is the half that decides whether a candidate is safe.
BACKENDS = [ClaudeProposer, OpenAIProposer]


@pytest.fixture(params=BACKENDS, ids=lambda c: c.provider)
def proposer(request):
    return request.param(recorded=RESPONSE.read_text(encoding="utf-8"))


@pytest.fixture
def proposals(proposer):
    return proposer.propose(CATALOG)


# --------------------------------------------------------------------------
# What survives
# --------------------------------------------------------------------------

def test_the_sound_candidates_come_through(proposals):
    accepted = {(p.attribute, p.cad_object, p.method) for p in proposals}
    assert ("length", "motor_housing", "bbox_size") in accepted
    assert ("mass", "motor_housing", "mass") in accepted


def test_arguments_are_rebuilt_from_the_typed_fields(proposals):
    length = next(p for p in proposals if p.attribute == "length")
    assert length.args == {"axis": "X"}
    mass = next(p for p in proposals if p.attribute == "mass")
    assert mass.args == {}, "no density override where the material supplies one"


def test_each_candidate_carries_confidence_and_a_rationale(proposals):
    """FREQ-4, and the reason a proposal is reviewable at all."""
    for proposal in proposals:
        assert 0.0 <= proposal.confidence <= 1.0
        assert len(proposal.rationale) > 20


def test_candidates_are_ranked(proposals):
    assert [p.confidence for p in proposals] == sorted(
        (p.confidence for p in proposals), reverse=True
    )


# --------------------------------------------------------------------------
# What does not -- the four ways a typed answer can still be fiction
# --------------------------------------------------------------------------

def test_an_invented_cad_object_is_dropped(proposer, proposals):
    assert not [p for p in proposals if "housing_v2" in p.cad_object]
    assert any("housing_v2" in reason for reason in proposer.dropped)


def test_an_attribute_the_part_does_not_have_is_dropped(proposer, proposals):
    assert not [p for p in proposals if p.attribute == "wallThickness"]
    assert any("wallThickness" in reason for reason in proposer.dropped)


def test_a_bounding_box_without_an_axis_is_dropped(proposer, proposals):
    """Filling in X would be the whole failure mode in one line: a plausible
    number from the wrong direction."""
    assert not [
        p for p in proposals
        if p.cad_object.endswith("#Housing") and p.method == "bbox_size"
    ]
    assert any("without an axis" in reason for reason in proposer.dropped)


def test_a_measurement_the_target_cannot_make_is_dropped(proposer, proposals):
    """The STEP node carries no material, so it offers no `mass`. The model
    suggested it anyway, which is exactly why the catalogue is checked."""
    assert not [
        p for p in proposals
        if p.cad_object.endswith("#Housing") and p.method == "mass"
    ]
    assert any("does not offer" in reason for reason in proposer.dropped)


def _one(proposer, **fields):
    """Replay a single candidate through the same backend."""
    candidate = {
        "sysml_part": "motorHousing", "attribute": "length",
        "cad_object": "motor_housing", "method": "bbox_size", "axis": "X",
        "confidence": 0.9, "rationale": "LENGTH_MM names the same quantity.",
        **fields,
    }
    replay = type(proposer)(recorded=json.dumps({"candidates": [candidate]}))
    return replay, replay.propose(CATALOG)


def test_a_density_from_the_model_is_dropped(proposer):
    """A density is a fact about the part. In a mapping entry it overrides the
    material the CAD side declares and goes stale when that changes -- so no
    proposer may supply one, whatever the server let through."""
    replay, proposals = _one(proposer, method="mass", attribute="mass", axis=None,
                             density_g_per_cm3=2.7)
    assert proposals == []
    assert any("density" in reason for reason in replay.dropped)


@pytest.mark.parametrize("confidence", [1.7, -0.1, "high", None, float("nan")])
def test_a_confidence_outside_zero_to_one_is_dropped(proposer, confidence):
    """In plain JSON mode nothing enforces the schema's bounds. A score of 1.7
    would outrank every honest candidate; "high" used to crash the run."""
    replay, proposals = _one(proposer, confidence=confidence)
    assert proposals == []
    assert any("confidence" in reason for reason in replay.dropped)


def test_a_candidate_that_is_not_an_object_is_dropped(proposer):
    replay = type(proposer)(recorded=json.dumps({"candidates": ["motorHousing.length"]}))
    assert replay.propose(CATALOG) == []
    assert any("not an object" in reason for reason in replay.dropped)


def test_every_rejection_is_recorded(proposer, proposals):
    """A proposer that invents names systematically is worth knowing about, and
    silence would hide it."""
    total = len(json.loads(RESPONSE.read_text(encoding="utf-8"))["candidates"])
    assert len(proposals) + len(proposer.dropped) == total


def test_an_empty_answer_is_not_an_error(proposer):
    empty = type(proposer)(recorded='{"candidates": []}')
    assert empty.propose(CATALOG) == []


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def test_every_proposal_records_what_produced_it(proposer, proposals):
    """NFREQ-1: a suggestion nobody can trace back to its source is not
    evidence, and "the AI proposed it" is not a source. With more than one
    backend the provider has to be recorded too -- two servers can serve the
    same model name and answer differently."""
    for proposal in proposals:
        assert proposal.proposed_by == proposer.name
        assert proposal.provenance["model"] == proposer.model
        assert proposal.provenance["provider"] == proposer.provider
        assert proposal.provenance["prompt_digest"]


def test_the_prompt_is_deterministic():
    """Same catalogue, same bytes -- otherwise the digest means nothing and the
    cached prefix never hits."""
    assert render_catalog(CATALOG) == render_catalog(CATALOG)
    assert prompt_digest(render_catalog(CATALOG)) == prompt_digest(render_catalog(CATALOG))


# --------------------------------------------------------------------------
# The excerpt
# --------------------------------------------------------------------------

def test_the_excerpt_carries_both_sides():
    excerpt = render_catalog(CATALOG)
    assert "part motorHousing : Housing" in excerpt
    assert "attribute length : LengthValue" in excerpt
    assert "cad_object motor_housing" in excerpt
    assert "parameter LENGTH_MM" in excerpt


def test_the_excerpt_says_what_can_be_measured():
    """So the model is not left to guess that a STEP node has no mass -- the
    commonest wrong suggestion, and it is answerable from the catalogue."""
    excerpt = render_catalog(CATALOG)
    assert "measurable: bbox_size, volume, face_count" in excerpt
    assert "measurable: bbox_size, volume, mass, face_count" in excerpt


def test_an_unaddressable_target_is_marked_as_such():
    ambiguous = CadTarget(
        adapter="step", reference="f.step#Bracket", kind="part", name="Bracket",
        methods=(), note="ambiguous name, matches 2 nodes",
    )
    excerpt = render_catalog(Catalog(parts=(PART,), targets=(ambiguous,)))
    assert "NOT ADDRESSABLE" in excerpt


def test_the_ai_proposer_needs_no_credentials_to_be_tested(proposer):
    """The property that keeps CI free and green: nothing above requires a key,
    and `requirements.txt` does not carry the SDK."""
    assert proposer._client is None
    proposer.propose(CATALOG)
    assert proposer._client is None


# --------------------------------------------------------------------------
# One prompt, one schema, several backends
# --------------------------------------------------------------------------

def test_every_backend_shares_the_verification():
    """The safety properties live in the base class, not in the backends.

    Stated as a test because it is the whole argument for pointing an arbitrary
    model at this system: a backend supplies `_ask` and nothing else, so no
    backend can weaken the checks that make an arbitrary answer safe to store.
    """
    from sysmlcad.propose_ai import LlmProposer

    for backend in BACKENDS:
        assert issubclass(backend, LlmProposer)
        assert "_verify" not in vars(backend), f"{backend.__name__} re-implements _verify"
        assert "propose" not in vars(backend), f"{backend.__name__} re-implements propose"
        assert "_ask" in vars(backend), f"{backend.__name__} must implement _ask"


def test_the_registry_lists_every_backend():
    """A backend nobody can select is a backend nobody will maintain."""
    assert set(AI_PROPOSERS) == {"claude", "openai"}


def test_the_baseline_is_still_the_default():
    """No credential, no network, no cost unless somebody explicitly asks for a
    model. This is what keeps CI green without a key."""
    from sysmlcad.propose import build_proposer

    assert build_proposer().name == "baseline:difflib"
    assert build_proposer(None).name == "baseline:difflib"


def test_the_json_schema_is_strict_enough_for_structured_outputs():
    """OpenAI-compatible strict mode rejects a schema that allows extra keys or
    leaves a property optional. Derived from the one pydantic model, so the two
    representations cannot drift apart."""
    pytest.importorskip("pydantic", reason="pydantic arrives with an AI SDK extra")
    schema = json_schema()
    candidate = schema["$defs"]["AiCandidate"]

    assert candidate["additionalProperties"] is False
    assert set(candidate["required"]) == set(candidate["properties"])
    assert "default" not in json.dumps(schema), "strict mode rejects defaults"


def test_a_model_without_a_name_is_refused_rather_than_guessed():
    """Picking a default model would run -- and bill -- something the user never
    chose. The error says which variable to set."""
    import os

    saved = os.environ.pop("SYSMLCAD_OPENAI_MODEL", None)
    try:
        with pytest.raises(RuntimeError, match="SYSMLCAD_OPENAI_MODEL"):
            OpenAIProposer()
    finally:
        if saved is not None:
            os.environ["SYSMLCAD_OPENAI_MODEL"] = saved


def test_a_truncated_claude_answer_yields_nothing_and_says_why():
    """`max_tokens` leaves `parsed_output` empty. It used to raise an
    AttributeError; half an answer is dropped, like on the OpenAI path."""
    pytest.importorskip("pydantic", reason="the Claude call builds its schema with pydantic")

    class _Response:
        stop_reason = "max_tokens"
        parsed_output = None
        id = "msg-1"

    class _Messages:
        def parse(self, **kwargs):
            return _Response()

    proposer = ClaudeProposer(client=type("Client", (), {"messages": _Messages()})())
    assert proposer.propose(CATALOG) == []
    assert any("max_tokens" in reason for reason in proposer.dropped)



def test_the_excerpt_states_the_axis_convention():
    """Without it a model can only assume X/Y/Z -- wrong for Chili3D, in the
    same plausible-looking way for every dimension."""
    chili = Catalog(parts=(PART,), targets=(SCRIPT,), axes={"length": "Y", "width": "Z", "height": "X"})
    assert "axes for bbox_size: length Y, width Z, height X" in render_catalog(chili)
    assert "length X" in render_catalog(CATALOG)
