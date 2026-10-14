"""Evaluation semantics: the three verdicts, tolerance, and dimension safety.

These are pure unit tests on `Requirement.evaluate` -- no geometry, no server.
The engine's arithmetic is worth pinning separately from the CAD pipeline,
because a wrong verdict is the one bug this whole system cannot tolerate.

The last group covers the other half of FREQ-5: an unconfirmed mapping entry
must not take part in a run, on the part side as much as on the attribute side.
"""

import shutil

import pytest

from sysmlcad import verify
from sysmlcad.adapters import Unsupported
from sysmlcad.mapping import AttributeMapping, Mapping, PartMapping, load_mapping
from sysmlcad.model import (
    BadTolerance,
    DimensionMismatch,
    Requirement,
    Run,
    RunContext,
    Verdict,
    parse_tolerance,
)
from sysmlcad.project import PROJECTS_DIR, load_project
from sysmlcad.units import ureg
from sysmlcad.verify import AdapterPool, _evaluate


def _req(limit="120 mm", operator="<="):
    return Requirement(
        requirement_id="MaxLength",
        element_id="test",
        subject="motorHousing",
        prop="length",
        operator=operator,
        limit=ureg.Quantity(limit),
    )


def test_within_the_limit_is_compliant():
    status, deviation = _req().evaluate(118 * ureg.mm)
    assert status == "compliant"
    assert deviation.magnitude == pytest.approx(-2)


def test_over_the_limit_without_tolerance_is_violated():
    status, deviation = _req().evaluate(123 * ureg.mm)
    assert status == "violated"
    assert deviation.magnitude == pytest.approx(3)


def test_over_the_limit_but_inside_tolerance():
    """The case a boolean verdict cannot express, and the one engineers
    actually negotiate over."""
    req = _req()
    status, _ = req.evaluate(121 * ureg.mm, parse_tolerance("2 mm", req.limit))
    assert status == "within_tolerance"


def test_tolerance_does_not_excuse_an_outright_violation():
    req = _req()
    status, _ = req.evaluate(125 * ureg.mm, parse_tolerance("2 mm", req.limit))
    assert status == "violated"


def test_tolerance_may_be_relative():
    req = _req()
    assert parse_tolerance("2%", req.limit).to("mm").magnitude == pytest.approx(2.4)


def test_tolerance_may_be_a_bare_number_in_the_limit_units():
    req = _req()
    assert parse_tolerance(0.5, req.limit).to("mm").magnitude == pytest.approx(0.5)


def test_no_tolerance_is_not_a_tolerance_of_zero():
    assert parse_tolerance(None, ureg.Quantity("120 mm")) is None


def test_units_are_converted_not_compared_numerically():
    """11.8 cm is inside a 120 mm limit. A system that compared magnitudes
    would call this a violation."""
    status, _ = _req().evaluate(11.8 * ureg.cm)
    assert status == "compliant"


def test_mismatched_dimensions_raise_rather_than_guess():
    """`DimensionMismatch` specifically: it is the type `verify.run()` turns
    into a gap, so a bare TypeError here would crash the run instead."""
    with pytest.raises(DimensionMismatch):
        _req().evaluate(0.5 * ureg.kg)


def test_a_strict_bound_is_violated_at_the_limit():
    assert _req(operator="<").evaluate(120 * ureg.mm)[0] == "violated"
    assert _req(operator="<=").evaluate(120 * ureg.mm)[0] == "compliant"


def test_an_equality_tolerance_works_in_both_directions():
    req = _req(limit="8 mm", operator="==")
    tol = parse_tolerance("0.1 mm", req.limit)
    assert req.evaluate(8.05 * ureg.mm, tol)[0] == "within_tolerance"
    assert req.evaluate(7.95 * ureg.mm, tol)[0] == "within_tolerance"
    assert req.evaluate(8.2 * ureg.mm, tol)[0] == "violated"


def test_an_unreadable_tolerance_is_a_mapping_fault():
    """`BadTolerance`, not whatever pint happened to raise -- so a run can
    report it as one gap."""
    with pytest.raises(BadTolerance):
        parse_tolerance("5 kg", ureg.Quantity("120 mm"))
    with pytest.raises(BadTolerance):
        parse_tolerance("abc%", ureg.Quantity("120 mm"))


def test_lower_bound_relaxes_downward():
    """Tolerance has to loosen the limit in the direction that helps, which is
    the opposite direction for >= than for <=."""
    req = _req(limit="100 mm", operator=">=")
    assert req.evaluate(99 * ureg.mm)[0] == "violated"
    assert req.evaluate(99 * ureg.mm, parse_tolerance("2 mm", req.limit))[0] == "within_tolerance"


# --------------------------------------------------------------------------
# FREQ-5 on the part side
# --------------------------------------------------------------------------

def _mapping(part_status: str) -> Mapping:
    """A minimal two-entry mapping. The attribute entry is always confirmed, so
    only the part's status is under test."""
    return Mapping(
        parts={
            "motorHousing": PartMapping(
                sysml_part="motorHousing",
                adapter="build123d",
                cad_object="motor_housing",
                status=part_status,
            )
        },
        attributes=[
            AttributeMapping(
                sysml_part="motorHousing",
                attribute="length",
                method="bbox_size",
                requirement="MaxLength",
                args={"axis": "X"},
                status="confirmed",
            )
        ],
        digest="test",
    )


def test_an_unconfirmed_part_is_a_gap_not_a_measurement():
    """A confirmed measurement method on an unconfirmed CAD object is still an
    unconfirmed mapping. Measuring it anyway would let an AI-written part entry
    take effect the moment it was written."""
    mapping = _mapping("proposed")
    entry = mapping.attributes[0]
    with pytest.raises(Unsupported, match="not confirmed"):
        _evaluate(_req(), entry, mapping, AdapterPool())


def test_a_confirmed_part_is_measured():
    """The same mapping with the part confirmed does reach the geometry -- the
    refusal above is about the status, not about a broken fixture."""
    mapping = _mapping("confirmed")
    verdict = _evaluate(_req(), mapping.attributes[0], mapping, AdapterPool())
    assert verdict.measured.to("mm").magnitude == pytest.approx(118.0)


# --------------------------------------------------------------------------
# The report says what happened, in words that fit the operator
# --------------------------------------------------------------------------

def _report(capsys, verdict: Verdict) -> str:
    verify.report(Run(RunContext(source="test"), [verdict]))
    return capsys.readouterr().out


def test_a_lower_bound_violation_reads_as_under(capsys):
    """The deviation column is signed; a sentence is not. "Over by -1 mm" for a
    bore that is too SMALL tells a reviewer the opposite of what happened."""
    req = _req(limit="8 mm", operator=">=")
    status, deviation = req.evaluate(7 * ureg.mm)
    out = _report(capsys, Verdict(req, 7 * ureg.mm, status, deviation, "m"))
    assert "under by 1 mm" in out
    assert "over by" not in out


def test_an_upper_bound_violation_still_reads_as_over(capsys):
    """The documented reference run, unchanged."""
    status, deviation = _req().evaluate(123 * ureg.mm)
    out = _report(capsys, Verdict(_req(), 123 * ureg.mm, status, deviation, "m"))
    assert "over by 3 mm" in out


def test_a_lower_bound_inside_tolerance_reads_as_short(capsys):
    req = _req(limit="8 mm", operator=">=")
    tol = parse_tolerance("2 mm", req.limit)
    status, deviation = req.evaluate(7 * ureg.mm, tol)
    out = _report(capsys, Verdict(req, 7 * ureg.mm, status, deviation, "m", tol))
    assert "falls short of 8 mm by 1 mm" in out
    assert "by -1" not in out


# --------------------------------------------------------------------------
# One bad mapping entry is one unchecked requirement, not a lost run
# --------------------------------------------------------------------------

@pytest.fixture
def motor_copy(tmp_path):
    """The motor housing project, copied so its mapping can be broken."""
    shutil.copytree(PROJECTS_DIR / "motor_housing", tmp_path / "motor_housing")
    return load_project("motor_housing", projects_dir=tmp_path)


def _edit_mapping(project, old: str, new: str) -> None:
    text = project.mapping_path.read_text(encoding="utf-8")
    assert old in text
    project.mapping_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_a_typo_in_args_is_one_gap(motor_copy):
    _edit_mapping(motor_copy, "      axis: X\n", "      axis: X\n      axsi: Y\n")
    result = verify.run(motor_copy)
    assert [v.requirement.requirement_id for v in result.verdicts] == ["MaxMass"]
    assert len(result.gaps) == 1 and result.gaps[0].startswith("MaxLength:")
    assert "axsi" in result.gaps[0]


def test_an_unreadable_tolerance_is_one_gap(motor_copy):
    _edit_mapping(motor_copy, 'tolerance: null                 # e.g.', 'tolerance: "5 kg"  # e.g.')
    result = verify.run(motor_copy)
    assert [v.requirement.requirement_id for v in result.verdicts] == ["MaxMass"]
    assert result.gaps[0].startswith("MaxLength:")
    assert "mapping fault" in result.gaps[0]


def test_a_requirement_the_extractor_cannot_read_is_a_gap(motor_copy, monkeypatch):
    """Before, an unreadable requirement was a `[warn]` line on stdout and the
    summary said "0 not checked" -- a claim of coverage the run did not have."""
    real = verify.load_with_context

    def with_a_skip(project, source=None):
        requirements, skipped, state = real(project, source)
        return requirements, skipped + ["MaxWidth: not extracted -- 2 comparisons"], state

    monkeypatch.setattr(verify, "load_with_context", with_a_skip)
    result = verify.run(motor_copy)
    assert len(result.verdicts) == 2
    assert result.gaps == ["MaxWidth: not extracted -- 2 comparisons"]


def test_a_confirmed_entry_wins_over_a_disabled_one_listed_first(motor_copy):
    """A `disabled` line left above its replacement must not turn a checked
    requirement into a gap."""
    text = motor_copy.mapping_path.read_text(encoding="utf-8")
    disabled = (
        "  - sysml_part: motorHousing\n    attribute: length\n    requirement: MaxLength\n"
        "    method: volume\n    status: disabled\n\n"
    )
    motor_copy.mapping_path.write_text(
        text.replace("attributes:\n", "attributes:\n" + disabled, 1), encoding="utf-8"
    )
    entry = load_mapping(motor_copy.mapping_path).for_requirement("MaxLength", "motorHousing")
    assert entry.status == "confirmed" and entry.method == "bbox_size"
    assert not verify.run(motor_copy).gaps
