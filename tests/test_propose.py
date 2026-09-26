"""The baseline proposer (SRS FREQ-4).

Most of these run against a hand-built catalogue rather than the real one: a
proposer is a ranking function, and ranking is easiest to pin down when the
candidate space is small enough to reason about completely.

The one that matters most is `test_a_length_attribute_is_never_proposed_against
_mass`. Everything else here is quality; that one is safety. A proposer that
crosses dimensions produces a plausible number from the wrong quantity, which is
the exact failure this project is built to prevent -- and it would arrive
wearing a confidence score.
"""

import pytest

from sysmlcad.adapters import CadTarget
from sysmlcad.catalog import Catalog, CatalogAttribute, CatalogPart
from sysmlcad.mapping import AttributeMapping, Mapping, PartMapping
from sysmlcad.project import list_projects, load_project
from sysmlcad.propose import DifflibProposer, gate, normalise, run, similarity
from sysmlcad.proposals import Proposal
from sysmlcad.verify import AdapterPool
from sysmlcad.units import ureg

MOTOR = load_project("motor_housing")

PART = CatalogPart(
    name="motorHousing",
    element_id="p1",
    definition="Housing",
    attributes=(
        CatalogAttribute("length", "a1", "LengthValue"),
        CatalogAttribute("mass", "a2", "MassValue"),
        CatalogAttribute("boreRadius", "a3", "LengthValue"),
        CatalogAttribute("stiffness", "a4", "SpringRate"),
    ),
)

SCRIPT = CadTarget(
    adapter="build123d",
    reference="motor_housing",
    kind="module",
    name="motor_housing",
    parameters={"LENGTH_MM": 118.0 * ureg.mm, "BORE_RADIUS_MM": 8.0 * ureg.mm},
    note="material AlSi10Mg",
)
STEP_NODE = CadTarget(
    adapter="step",
    reference="fixtures/step/gearbox.step#Cover",
    kind="part",
    name="Cover",
    methods=("bbox_size", "volume", "face_count"),
    note="no material in the file",
)
AMBIGUOUS = CadTarget(
    adapter="step",
    reference="fixtures/step/x.step#Bracket",
    kind="part",
    name="Bracket",
    methods=(),
    note="ambiguous name",
)

CATALOG = Catalog(parts=(PART,), targets=(SCRIPT, STEP_NODE, AMBIGUOUS), source="test")


def _proposals(catalog=CATALOG):
    return DifflibProposer().propose(catalog)


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def test_the_three_naming_conventions_meet_in_the_middle():
    """SysML camelCase, Python snake_case and CAD SCREAMING_CASE describe the
    same things; a proposer blind to that is useless on its first real model."""
    assert normalise("motorHousing") == "motor housing"
    assert normalise("motor_housing") == "motor housing"
    assert normalise("HOUSING_LENGTH_MM") == "housing length mm"
    assert normalise("gearbox.step#Housing") == "gearbox step housing"


def test_a_contained_name_scores_well():
    """The commonest real shape: the CAD name is the SysML name with the
    assembly's name in front of it."""
    assert similarity("Housing", "motor_housing") > 0.7
    assert similarity("Housing", "Housing") == 1.0
    assert similarity("Housing", "shaft") < 0.5


# --------------------------------------------------------------------------
# The dimension filter -- the safety property
# --------------------------------------------------------------------------

def test_a_length_attribute_is_never_proposed_against_mass():
    for proposal in _proposals():
        if proposal.attribute in ("length", "boreRadius"):
            assert proposal.method != "mass"


def test_a_mass_attribute_is_never_proposed_against_a_bounding_box():
    for proposal in _proposals():
        if proposal.attribute == "mass":
            assert proposal.method == "mass"


def test_an_attribute_of_unknown_type_is_not_forced_into_a_measurement():
    """`SpringRate` is not in `_VALUE_TYPES`, so no dimension filter applies.
    The proposer may still suggest something, but nothing here may pretend the
    dimension was checked -- the gate reports `unknown` and the human decides."""
    stiffness = [p for p in _proposals() if p.attribute == "stiffness"]
    assert stiffness, "the test needs candidates to say anything"
    for proposal in stiffness:
        assert "weak" in proposal.rationale


# --------------------------------------------------------------------------
# Method and axis choice
# --------------------------------------------------------------------------

def test_the_axis_comes_from_the_name_and_says_so():
    """Which axis a `length` is measured along is a convention, not a fact. A
    proposal that used it silently would hide its weakest assumption."""
    length = next(p for p in _proposals() if p.attribute == "length")
    assert length.args == {"axis": "X"}
    assert "convention" in length.rationale


def test_an_attribute_with_no_obvious_axis_gets_no_bounding_box_proposal():
    """`boreRadius` is a length, but no axis of a bounding box is its radius.
    Guessing X here would be the whole failure mode in miniature."""
    assert not [
        p for p in _proposals()
        if p.attribute == "boreRadius" and p.method == "bbox_size"
    ]


def test_a_named_parameter_is_the_strongest_evidence():
    """`LENGTH_MM` in a script is a deliberate statement by whoever wrote it."""
    best = max(
        (p for p in _proposals() if p.attribute == "length"),
        key=lambda p: p.confidence,
    )
    assert best.cad_object == "motor_housing"
    assert "LENGTH_MM" in best.rationale


def test_an_unaddressable_target_is_never_proposed():
    """An ambiguous node cannot be measured, so proposing it would only produce
    a gap with a confidence score attached."""
    assert not [p for p in _proposals() if "Bracket" in p.cad_object]


def test_a_target_without_the_method_is_not_proposed():
    """The STEP node carries no material, so its catalogue entry does not offer
    `mass` -- and no proposal may invent it."""
    assert not [
        p for p in _proposals()
        if p.cad_object == STEP_NODE.reference and p.method == "mass"
    ]


# --------------------------------------------------------------------------
# Ranking and the run
# --------------------------------------------------------------------------

def test_candidates_come_back_ranked():
    confidences = [p.confidence for p in _proposals()]
    assert confidences == sorted(confidences, reverse=True)


def test_every_proposal_explains_itself():
    """FREQ-4: a candidate carries a confidence value and a short rationale."""
    for proposal in _proposals():
        assert 0.0 < proposal.confidence <= 1.0
        assert len(proposal.rationale) > 20
        assert proposal.proposed_by == "baseline:difflib"


def test_an_already_confirmed_attribute_is_not_proposed_again():
    mapping = Mapping(
        parts={"motorHousing": PartMapping("motorHousing", "build123d", "motor_housing",
                                           status="confirmed")},
        attributes=[AttributeMapping("motorHousing", "length", "bbox_size",
                                     requirement="MaxLength", args={"axis": "X"},
                                     status="confirmed")],
        digest="test",
    )
    kept, _dropped = run(MOTOR, top=3, catalog=CATALOG, mapping=mapping)
    assert not [p for p in kept if p.attribute == "length"]


def test_a_candidate_naming_another_object_for_a_mapped_part_is_dropped():
    """Gated on the object it names, and refused because the part already
    stands for a different one. Before, it was gated on the existing object
    and stored looking sound."""
    mapping = Mapping(
        parts={"motorHousing": PartMapping("motorHousing", "build123d", "motor_housing",
                                           status="confirmed")},
        attributes=[],
        digest="test",
    )
    candidate = Proposal(
        id="", sysml_part="motorHousing", attribute="length", adapter="step",
        cad_object="fixtures/step/motor_housing.step", method="bbox_size",
        args={"axis": "X"}, confidence=0.9,
    )
    kept, dropped = gate([candidate], mapping, CATALOG, {}, AdapterPool())
    assert kept == []
    [(_, check)] = dropped
    assert any("already mapped" in p.detail for p in check.problems)


def test_top_limits_what_reaches_the_review_queue():
    empty = Mapping(parts={}, attributes=[], digest="empty")
    one, _ = run(MOTOR, top=1, catalog=CATALOG, mapping=empty)
    three, _ = run(MOTOR, top=3, catalog=CATALOG, mapping=empty)
    per_attribute = {}
    for proposal in one:
        per_attribute[proposal.attribute] = per_attribute.get(proposal.attribute, 0) + 1
    assert max(per_attribute.values()) == 1
    assert len(three) >= len(one)


def test_proposing_writes_nothing_to_the_mapping():
    """The store separation, checked rather than assumed: a proposer that could
    reach mapping.yaml would make FREQ-5 a matter of discipline."""
    path = MOTOR.mapping_path
    before = path.read_text(encoding="utf-8")
    run(MOTOR, top=3, catalog=CATALOG, mapping=Mapping(parts={}, attributes=[], digest="e"))
    assert path.read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------
# The scoreboard -- a floor, not a target
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, floor", [("motor_housing", 2), ("gearbox", 11), ("box1", 3), ("box2", 3)])
def test_the_baseline_does_not_regress(name, floor):
    """Pins the number the AI has to beat, per project.

    Honest about what it is: the baseline was tuned *after* seeing these gold
    sets, so a full score is a training score, not a held-out one. Its job is
    to stop a later change quietly making the baseline worse -- and to stop
    anyone claiming the AI helps without beating it.
    """
    from sysmlcad.catalog import load_catalog
    from sysmlcad.score import load_gold, score

    project = load_project(name)
    result = score(project, DifflibProposer(), load_gold(project), load_catalog(project))
    assert result.hit_at_1 >= floor, f"{name}: baseline regressed: {result.false_positives}"
    assert not result.false_positives, f"{name}: {result.false_positives}"


def test_the_proposer_does_not_invent_a_density():
    """Mass on an object with no material needs a number nobody has stated.
    Substituting one would be the failure this project is built to prevent, so
    the proposer must not offer it -- even though it makes the score worse."""
    from sysmlcad.catalog import load_catalog

    for name in list_projects():
        for proposal in DifflibProposer().propose(load_catalog(load_project(name))):
            if proposal.method == "mass":
                assert "density_g_per_cm3" not in proposal.args


def test_part_conflicts_are_summarised_once_per_part(capsys):
    """Every candidate on another object than its part's mapped one is refused
    for the same reason. One line each buried the rejections that say
    something; one line per part keeps them visible."""
    from sysmlcad.gates import PART_CONFLICT, GateResult, MappingCheck
    from sysmlcad.propose import report

    def conflict(attribute, cad_object):
        candidate = Proposal(id="", sysml_part="housing", attribute=attribute,
                             adapter="step", cad_object=cad_object, method="bbox_size")
        check = MappingCheck("housing", attribute, cad_object, "bbox_size", "confirmed",
                             results=(GateResult("uniqueness", "invalid", "...", code=PART_CONFLICT),))
        return candidate, check

    report([], [conflict("width", "a.step#Housing"), conflict("height", "a.step#Housing"),
                conflict("width", "gearbox")], stored=0)
    out = capsys.readouterr().out
    assert "3 named another CAD object" in out
    assert out.count("housing:") == 1
    assert "a.step#Housing, gearbox" in out



def test_the_axis_comes_from_the_project_s_convention():
    """Configured, not hard-coded: with Chili3D's orientation in the catalogue,
    `length` is proposed along Y -- and the rationale says where that came from."""
    chili = Catalog(parts=(PART,), targets=(SCRIPT,), source="test",
                    axes={"length": "Y", "width": "Z", "height": "X"})
    length = next(p for p in DifflibProposer().propose(chili)
                  if p.attribute == "length" and p.method == "bbox_size")
    assert length.args == {"axis": "Y"}
    assert "axis convention" in length.rationale
