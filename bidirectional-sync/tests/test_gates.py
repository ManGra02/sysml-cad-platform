"""The gates: is the mapping sound, as opposed to is the design compliant.

The distinction is the point of the module and the thing these tests defend. In
particular `test_an_implausible_ratio_is_never_invalid`: a part ten times over
its limit might be a wrong mapping or a real, large violation, and a gate that
picked one would be deciding a verdict -- which is `verify.py`'s job, under
rules these gates do not have.
"""

import pytest

from sysmlcad.catalog import Catalog, CatalogAttribute, CatalogPart
from sysmlcad.project import list_projects, load_project
from sysmlcad.gates import (
    check_mapping,
    gate_dimension,
    gate_plausibility,
    gate_uniqueness,
    unused_parts,
)
from sysmlcad.mapping import AttributeMapping, Mapping, PartMapping
from sysmlcad.model import Requirement
from sysmlcad.units import ureg
from sysmlcad.verify import AdapterPool

HOUSING = CatalogPart(
    name="motorHousing",
    element_id="p1",
    definition="Housing",
    attributes=(
        CatalogAttribute(name="length", element_id="a1", type_name="LengthValue"),
        CatalogAttribute(name="mass", element_id="a2", type_name="MassValue"),
        CatalogAttribute(name="stiffness", element_id="a3", type_name="SpringRate"),
    ),
)
CATALOG = Catalog(parts=(HOUSING,), source="test")


def _entry(**kwargs) -> AttributeMapping:
    return AttributeMapping(**{
        "sysml_part": "motorHousing",
        "attribute": "length",
        "method": "bbox_size",
        "requirement": "MaxLength",
        "args": {"axis": "X"},
        "status": "confirmed",
        **kwargs,
    })


def _mapping(*entries: AttributeMapping) -> Mapping:
    return Mapping(
        parts={
            "motorHousing": PartMapping(
                sysml_part="motorHousing", adapter="build123d",
                cad_object="motor_housing", status="confirmed",
            )
        },
        attributes=list(entries),
        digest="test",
    )


def _requirement(limit="120 mm") -> Requirement:
    return Requirement(
        requirement_id="MaxLength", element_id="r1", subject="motorHousing",
        prop="length", operator="<=", limit=ureg.Quantity(limit),
    )

MOTOR = load_project("motor_housing")


# --------------------------------------------------------------------------
# The real mapping, end to end
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", list_projects())
def test_the_committed_mapping_passes_every_gate(name):
    """Every project's committed mapping, against its own capture."""
    checks = check_mapping(load_project(name))
    assert checks, f"{name}: no entries checked -- the mapping or the capture moved"
    for check in checks:
        assert check.verdict == "valid", f"{name} {check.sysml_part}.{check.attribute}: {check.problems}"


def test_a_disabled_entry_is_not_gated():
    """Disabling an entry is a decision, not an oversight. Reporting problems
    with it would be reporting work nobody intends to do."""
    mapping = _mapping(_entry(status="disabled"))
    assert check_mapping(MOTOR, mapping, CATALOG, [_requirement()], AdapterPool()) == []


def test_an_unconfirmed_entry_is_still_gated():
    """Checking a proposal before a human confirms it is what the gates are
    for, so `status: proposed` must not exempt an entry from them."""
    mapping = _mapping(_entry(status="proposed"))
    checks = check_mapping(MOTOR, mapping, CATALOG, [_requirement()], AdapterPool())
    assert len(checks) == 1
    assert checks[0].verdict == "valid"


# --------------------------------------------------------------------------
# Dimension
# --------------------------------------------------------------------------

def test_a_length_measurement_for_a_mass_attribute_is_invalid():
    entry = _entry(attribute="mass", requirement="MaxMass", method="bbox_size")
    result = gate_dimension(entry, CATALOG, None, 60 * ureg.mm)
    assert result.verdict == "invalid"
    assert "[mass]" in result.detail


def test_a_measurement_that_contradicts_the_limit_is_invalid():
    """The attribute's type and the requirement's limit are two independent
    statements of the same dimension. Either one catching a mismatch is enough."""
    result = gate_dimension(_entry(), CATALOG, _requirement("0.9 kg"), 118 * ureg.mm)
    assert result.verdict == "invalid"
    assert "MaxLength" in result.detail


def test_an_unknown_value_type_is_unknown_not_valid():
    """`_VALUE_TYPES` does not know SpringRate. "I could not check" must not be
    reported as "I checked and it is fine"."""
    entry = _entry(attribute="stiffness", requirement="")
    result = gate_dimension(entry, CATALOG, None, 5 * ureg.newton / ureg.mm)
    assert result.verdict == "unknown"


def test_the_matching_dimension_is_valid():
    result = gate_dimension(_entry(), CATALOG, _requirement(), 118 * ureg.mm)
    assert result.verdict == "valid"


def test_an_unreadable_tolerance_is_a_dimension_fault():
    """A run meets `tolerance: "5 kg"` on a length only as a gap; the gates are
    where it gets named."""
    result = gate_dimension(_entry(tolerance="5 kg"), CATALOG, _requirement(), 118 * ureg.mm)
    assert result.verdict == "invalid"
    assert "5 kg" in result.detail


# --------------------------------------------------------------------------
# Existence
# --------------------------------------------------------------------------

def test_an_attribute_the_model_does_not_have_is_invalid():
    mapping = _mapping(_entry(attribute="wheelbase"))
    check = check_mapping(MOTOR, mapping, CATALOG, [_requirement()], AdapterPool())[0]
    assert check.verdict == "invalid"
    problem = next(p for p in check.problems if p.gate == "existence")
    assert "wheelbase" in problem.detail
    assert "length" in problem.detail, "the message should say what is available"


def test_a_malformed_argument_is_invalid_not_a_crash():
    """A typo in `args:` used to escape the gates as a TypeError, taking every
    other entry's check with it."""
    mapping = _mapping(_entry(args={"axis": "X", "axsi": "Y"}))
    check = check_mapping(MOTOR, mapping, CATALOG, [_requirement()], AdapterPool())[0]
    assert check.verdict == "invalid"
    assert any("axsi" in p.detail for p in check.problems)


def test_a_measurement_the_adapter_cannot_make_is_invalid():
    """A STEP file with no material cannot yield a mass. Reported here as a bad
    mapping; at verification time the same entry is a gap. Both are true."""
    mapping = Mapping(
        parts={"motorHousing": PartMapping(
            sysml_part="motorHousing", adapter="step",
            cad_object="fixtures/step/motor_housing.step", status="confirmed",
        )},
        attributes=[_entry(attribute="mass", requirement="MaxMass", method="mass", args={})],
        digest="test",
    )
    check = check_mapping(MOTOR, mapping, CATALOG, [], AdapterPool())[0]
    assert check.verdict == "invalid"
    assert any("material" in p.detail for p in check.problems)


# --------------------------------------------------------------------------
# Uniqueness
# --------------------------------------------------------------------------

def test_two_confirmed_entries_for_one_requirement_are_invalid():
    """`Mapping.for_requirement` takes the first match, so the second entry
    would never be used and never be noticed."""
    first = _entry()
    second = _entry(attribute="width", method="bbox_size", args={"axis": "Y"})
    mapping = _mapping(first, second)
    assert gate_uniqueness(first, mapping).verdict == "invalid"


def test_one_requirement_on_two_parts_is_not_a_duplicate():
    """A definition satisfied by two parts is checked once per part, so each
    part legitimately carries its own entry for it -- keyed exactly as
    `Mapping.for_requirement` looks them up."""
    housing = _entry()
    spare = _entry(sysml_part="spareHousing")
    mapping = _mapping(housing, spare)
    mapping.parts["spareHousing"] = PartMapping(
        sysml_part="spareHousing", adapter="step",
        cad_object="fixtures/step/motor_housing.step", status="confirmed",
    )
    assert gate_uniqueness(housing, mapping).verdict == "valid"
    assert gate_uniqueness(spare, mapping).verdict == "valid"


def test_a_proposed_duplicate_does_not_invalidate_a_confirmed_entry():
    """Only confirmed entries take part in a run, so only they can collide."""
    confirmed = _entry()
    proposed = _entry(attribute="width", status="proposed")
    assert gate_uniqueness(confirmed, _mapping(confirmed, proposed)).verdict == "valid"


def test_one_cad_object_for_two_parts_is_flagged_but_not_condemned():
    """Suspicious, not wrong: a part and a variant can legitimately share an
    object. The gate says look at it."""
    mapping = _mapping(_entry())
    mapping.parts["cover"] = PartMapping(
        sysml_part="cover", adapter="build123d",
        cad_object="motor_housing", status="confirmed",
    )
    result = gate_uniqueness(_entry(), mapping)
    assert result.verdict == "unknown"
    assert "cover" in result.detail


# --------------------------------------------------------------------------
# Plausibility
# --------------------------------------------------------------------------

def test_a_measurement_near_the_limit_is_plausible():
    assert gate_plausibility(_requirement(), 118 * ureg.mm).verdict == "valid"


def test_an_implausible_ratio_is_never_invalid():
    """The load-bearing test of this module. 118 metres against a 120 mm limit
    is either a unit confusion or an enormous violation -- and a gate that
    picked one would be deciding a verdict."""
    result = gate_plausibility(_requirement(), 118 * ureg.m)
    assert result.verdict == "unknown"
    assert "1e+03" in result.detail or "983" in result.detail


def test_plausibility_says_nothing_without_a_limit():
    assert gate_plausibility(None, 118 * ureg.mm).verdict == "unknown"


# --------------------------------------------------------------------------
# Loose ends
# --------------------------------------------------------------------------

def test_a_part_no_attribute_uses_is_reported():
    mapping = _mapping(_entry())
    mapping.parts["orphan"] = PartMapping(
        sysml_part="orphan", adapter="build123d", cad_object="gearbox",
    )
    assert unused_parts(mapping) == ["orphan"]


def test_gates_and_verdicts_are_independent():
    """A part that is too long is a violation, not a bad mapping. The gates must
    stay quiet about it -- this is the confusion the whole module exists to
    prevent."""
    over_limit = 500 * ureg.mm
    requirement = _requirement("120 mm")
    assert requirement.evaluate(over_limit)[0] == "violated"
    assert gate_dimension(_entry(), CATALOG, requirement, over_limit).verdict == "valid"
    assert gate_plausibility(requirement, over_limit).verdict != "invalid"



# --------------------------------------------------------------------------
# The axis convention
# --------------------------------------------------------------------------

def test_an_entry_against_the_axis_convention_is_flagged_not_condemned():
    """A part may lie on its side, so this is never `invalid` -- but when a
    project's `axes:` changes, every entry left on the old axis must show up
    rather than measure the wrong extent in silence."""
    from sysmlcad.gates import off_axis

    chili = Catalog(parts=(HOUSING,), source="test",
                    axes={"length": "Y", "width": "Z", "height": "X"})
    assert off_axis(_entry(), chili) is not None, "length along X, convention says Y"
    assert off_axis(_entry(args={"axis": "Y"}), chili) is None
    assert off_axis(_entry(), CATALOG) is None, "the default convention puts length on X"

    check = check_mapping(MOTOR, _mapping(_entry()), chili, [_requirement()], AdapterPool())[0]
    plausibility = next(r for r in check.results if r.gate == "plausibility")
    assert plausibility.verdict == "unknown"
    assert check.verdict == "unknown", "flagged, never invalid"
