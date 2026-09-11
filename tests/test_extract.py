"""Checks the graph traversal against the real API structure.

The element graph below is reconstructed from an actual %publish dump:
RequirementDefinition -> FeatureMembership -> AttributeUsage[maxLength]
-> FeatureValue -> OperatorExpression("[") -> {LiteralInteger, unit},
plus RequirementConstraintMembership -> ConstraintUsage -> "<=".

Running without a network is the point: these tests pin the traversal rules,
which is where the subtle breakage lives.
"""

import json
from pathlib import Path

import pytest

from sysmlcad.extract import elements_to_requirements, resolve_satisfies

#: A captured publish of models/gearbox.sysml -- three parts, and two of the
#: four satisfy links written as dotted paths. Nothing else in the repository
#: exercises a feature chain.
GEARBOX = Path(__file__).resolve().parents[1] / "projects" / "gearbox" / "elements.json"


def _graph(name, value, unit_short, operator="<="):
    p = name.lower()
    return [
        {"@id": f"{p}-req", "@type": "RequirementDefinition", "declaredName": name,
         "ownedRelationship": [{"@id": f"{p}-fm"}, {"@id": f"{p}-rcm"},
                               {"@id": f"{p}-sm"}]},
        # Subject
        {"@id": f"{p}-sm", "@type": "SubjectMembership",
         "ownedRelatedElement": [{"@id": f"{p}-subj"}]},
        {"@id": f"{p}-subj", "@type": "ReferenceUsage", "declaredName": "housing",
         "owner": {"@id": f"{p}-req"}},
        # Limit value with its unit
        {"@id": f"{p}-fm", "@type": "FeatureMembership",
         "source": [{"@id": f"{p}-req"}],
         "ownedRelatedElement": [{"@id": f"{p}-au"}]},
        {"@id": f"{p}-au", "@type": "AttributeUsage", "declaredName": f"max{name}",
         "ownedRelationship": [{"@id": f"{p}-fv"}]},
        {"@id": f"{p}-fv", "@type": "FeatureValue",
         "ownedRelatedElement": [{"@id": f"{p}-bracket"}]},
        {"@id": f"{p}-bracket", "@type": "OperatorExpression", "operator": "[",
         "ownedRelationship": [{"@id": f"{p}-pm1"}, {"@id": f"{p}-pm2"}]},
        {"@id": f"{p}-pm1", "@type": "ParameterMembership",
         "ownedRelatedElement": [{"@id": f"{p}-f1"}]},
        {"@id": f"{p}-f1", "@type": "Feature",
         "ownedRelationship": [{"@id": f"{p}-fv1"}]},
        {"@id": f"{p}-fv1", "@type": "FeatureValue",
         "ownedRelatedElement": [{"@id": f"{p}-lit"}]},
        {"@id": f"{p}-lit", "@type": "LiteralInteger", "value": value},
        {"@id": f"{p}-pm2", "@type": "ParameterMembership",
         "ownedRelatedElement": [{"@id": f"{p}-f2"}]},
        {"@id": f"{p}-f2", "@type": "Feature",
         "ownedRelationship": [{"@id": f"{p}-fv2"}]},
        {"@id": f"{p}-fv2", "@type": "FeatureValue",
         "ownedRelatedElement": [{"@id": f"{p}-fre"}]},
        {"@id": f"{p}-fre", "@type": "FeatureReferenceExpression",
         "ownedRelationship": [{"@id": f"{p}-mem"}]},
        {"@id": f"{p}-mem", "@type": "Membership", "target": [{"@id": f"unit-{unit_short}"}]},
        {"@id": f"unit-{unit_short}", "@type": "AttributeUsage",
         "declaredShortName": unit_short, "isLibraryElement": True},
        # Constraint carrying the comparison operator
        {"@id": f"{p}-rcm", "@type": "RequirementConstraintMembership",
         "ownedRelatedElement": [{"@id": f"{p}-cu"}]},
        {"@id": f"{p}-cu", "@type": "ConstraintUsage",
         "ownedRelationship": [{"@id": f"{p}-rem"}]},
        {"@id": f"{p}-rem", "@type": "ResultExpressionMembership",
         "ownedRelatedElement": [{"@id": f"{p}-cmp"}]},
        {"@id": f"{p}-cmp", "@type": "OperatorExpression", "operator": operator},
    ]


def _satisfy(name, part_name):
    """`satisfy <name>Check by <part>;` as the API actually serialises it.

    Two branches off one SatisfyRequirementUsage: the ReferenceSubsetting side
    leads to the RequirementDefinition, the SubjectMembership side to the
    PartUsage.
    """
    p = name.lower()
    return [
        {"@id": f"{p}-sat", "@type": "SatisfyRequirementUsage",
         "ownedRelationship": [{"@id": f"{p}-rs"}, {"@id": f"{p}-satsm"}]},
        # -> requirement definition
        {"@id": f"{p}-rs", "@type": "ReferenceSubsetting",
         "general": {"@id": f"{p}-requsage"}},
        {"@id": f"{p}-requsage", "@type": "RequirementUsage",
         "declaredName": f"{p}Check",
         "ownedRelationship": [{"@id": f"{p}-ft"}]},
        {"@id": f"{p}-ft", "@type": "FeatureTyping", "general": {"@id": f"{p}-req"}},
        # -> part usage
        {"@id": f"{p}-satsm", "@type": "SubjectMembership",
         "memberElement": {"@id": f"{p}-satref"}},
        {"@id": f"{p}-satref", "@type": "ReferenceUsage",
         "ownedRelationship": [{"@id": f"{p}-satfv"}]},
        {"@id": f"{p}-satfv", "@type": "FeatureValue",
         "memberElement": {"@id": f"{p}-satfre"}},
        {"@id": f"{p}-satfre", "@type": "FeatureReferenceExpression",
         "ownedRelationship": [{"@id": f"{p}-satmem"}]},
        {"@id": f"{p}-satmem", "@type": "Membership",
         "memberElement": {"@id": f"part-{part_name}"}},
        {"@id": f"part-{part_name}", "@type": "PartUsage", "declaredName": part_name},
    ]


def test_extracts_value_unit_and_operator():
    reqs = elements_to_requirements(_graph("MaxLength", 120, "mm"))
    assert len(reqs) == 1
    r = reqs[0]
    assert r.requirement_id == "MaxLength"
    assert r.operator == "<="
    assert r.limit.magnitude == 120
    assert str(r.limit.units) == "millimeter"
    assert r.subject == "housing"


def test_requirements_stay_separate():
    """The core traversal risk: does MaxLength's subtree reach into MaxMass's
    limit value?"""
    reqs = elements_to_requirements(_graph("MaxLength", 120, "mm")
                                    + _graph("MaxMass", 0.9, "kg"))
    values = {r.requirement_id: (r.limit.magnitude, str(r.limit.units)) for r in reqs}
    assert values == {"MaxLength": (120, "millimeter"), "MaxMass": (0.9, "kilogram")}


def test_incomplete_requirement_is_discarded():
    graph = [e for e in _graph("MaxLength", 120, "mm") if e["@id"] != "maxlength-cmp"]
    assert elements_to_requirements(graph) == []


def test_library_elements_are_ignored():
    graph = _graph("MaxLength", 120, "mm")
    graph[0]["isLibraryElement"] = True
    assert elements_to_requirements(graph) == []


# --------------------------------------------------------------------------
# The satisfy link -- what anchors a requirement to a physical part
# --------------------------------------------------------------------------

def test_satisfy_link_resolves_the_real_subject():
    """Without the satisfy link the best available answer is the subject
    *parameter* of the definition ("housing"). With it, the answer is the part
    the model actually says is constrained ("motorHousing"). Those are
    different things, and only the second one can be mapped to CAD."""
    graph = _graph("MaxLength", 120, "mm") + _satisfy("MaxLength", "motorHousing")
    reqs = elements_to_requirements(graph)
    assert len(reqs) == 1
    assert reqs[0].subject == "motorHousing"
    assert reqs[0].subject_id == "part-motorHousing"


def test_subject_falls_back_when_no_satisfy_link_exists():
    reqs = elements_to_requirements(_graph("MaxLength", 120, "mm"))
    assert reqs[0].subject == "housing"
    assert reqs[0].subject_id == ""


def test_satisfy_links_do_not_cross_between_requirements():
    """Two requirements on two different parts must not swap subjects -- the
    failure mode that would silently measure the wrong component."""
    graph = (
        _graph("MaxLength", 120, "mm") + _satisfy("MaxLength", "motorHousing")
        + _graph("MaxMass", 0.9, "kg") + _satisfy("MaxMass", "gearCover")
    )
    subjects = {r.requirement_id: r.subject for r in elements_to_requirements(graph)}
    assert subjects == {"MaxLength": "motorHousing", "MaxMass": "gearCover"}


def test_satisfy_resolution_records_a_link_path():
    """The path is the evidence for *why* two elements are considered related.
    Change-impact analysis reports it; without it a result is an assertion."""
    graph = _graph("MaxLength", 120, "mm") + _satisfy("MaxLength", "motorHousing")
    resolved = resolve_satisfies(graph)
    assert len(resolved) == 1
    part, path = resolved["maxlength-req"]
    assert part["declaredName"] == "motorHousing"
    assert path[0] == "maxlength-sat"
    assert "part-motorHousing" in path


# --------------------------------------------------------------------------
# Dotted paths -- against a real capture, because this one was found the hard way
# --------------------------------------------------------------------------

@pytest.mark.skipif(not GEARBOX.is_file(), reason="gearbox capture missing")
def test_a_dotted_satisfy_resolves_to_the_last_link():
    """`satisfy housingLengthCheck by gearbox.housing` is about the HOUSING.

    A dotted path serialises as an anonymous Feature owning one FeatureChaining
    per segment, in order -- gearbox first, housing last. Searching for the
    nearest PartUsage finds `gearbox` and is wrong in the worst available way:
    it measures the whole assembly and reports a confident verdict for an object
    the requirement is not about. This is what the live model did before the
    chain was followed, and all four requirements resolved to `gearbox`.
    """
    requirements = {
        r.requirement_id: r
        for r in elements_to_requirements(json.loads(GEARBOX.read_text(encoding="utf-8")))
    }

    assert requirements["MaxHousingLength"].subject == "housing"
    assert requirements["MaxCoverThickness"].subject == "cover"
    assert requirements["MinBoreRadius"].subject == "housing"
    # ... and a plain, undotted reference still resolves to itself.
    assert requirements["MaxAssemblyMass"].subject == "gearbox"


@pytest.mark.skipif(not GEARBOX.is_file(), reason="gearbox capture missing")
def test_every_subject_is_a_real_element():
    """Each subject carries the id of the element it came from, so a verdict can
    be traced back to the model rather than to a name that merely matched."""
    for requirement in elements_to_requirements(
        json.loads(GEARBOX.read_text(encoding="utf-8"))
    ):
        assert requirement.subject_id, f"{requirement.requirement_id} has no subject id"


@pytest.mark.skipif(not GEARBOX.is_file(), reason="gearbox capture missing")
def test_the_chain_is_recorded_in_the_link_path():
    """Change-impact analysis has to be able to say *why* it thinks a
    requirement is about a part. For a dotted path that reason is the chain."""
    elements = json.loads(GEARBOX.read_text(encoding="utf-8"))
    by_id = {e["@id"]: e for e in elements if "@id" in e}
    resolved = resolve_satisfies(elements, by_id)

    housing = next(
        (part, path) for part, path in resolved.values()
        if part.get("declaredName") == "housing"
    )
    part, path = housing
    assert part["@id"] in path
    assert len(path) > 3, "the path should record the road, not just the destination"
