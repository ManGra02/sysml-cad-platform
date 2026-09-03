"""The AI proposer, driven by a recorded response.

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
"""

import json
from pathlib import Path

import pytest

from sysmlcad.adapters import CadTarget
from sysmlcad.catalog import Catalog, CatalogAttribute, CatalogPart
from sysmlcad.propose_ai import ClaudeProposer, prompt_digest, render_catalog
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


@pytest.fixture
def proposer():
    return ClaudeProposer(recorded=RESPONSE.read_text(encoding="utf-8"))


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


def test_every_rejection_is_recorded(proposer, proposals):
    """A proposer that invents names systematically is worth knowing about, and
    silence would hide it."""
    total = len(json.loads(RESPONSE.read_text(encoding="utf-8"))["candidates"])
    assert len(proposals) + len(proposer.dropped) == total


def test_an_empty_answer_is_not_an_error(proposer):
    empty = ClaudeProposer(recorded='{"candidates": []}')
    assert empty.propose(CATALOG) == []


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def test_every_proposal_records_what_produced_it(proposals):
    """NFREQ-1: a suggestion nobody can trace back to its source is not
    evidence, and "the AI proposed it" is not a source."""
    for proposal in proposals:
        assert proposal.proposed_by == "ai:claude-opus-5"
        assert proposal.provenance["model"] == "claude-opus-5"
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
