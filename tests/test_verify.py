"""Evaluation semantics: the three verdicts, tolerance, and dimension safety.

These are pure unit tests on `Requirement.evaluate` -- no geometry, no server.
The engine's arithmetic is worth pinning separately from the CAD pipeline,
because a wrong verdict is the one bug this whole system cannot tolerate.
"""

import pytest

from sysmlcad.model import Requirement, parse_tolerance
from sysmlcad.units import ureg


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
    with pytest.raises(TypeError):
        _req().evaluate(0.5 * ureg.kg)


def test_lower_bound_relaxes_downward():
    """Tolerance has to loosen the limit in the direction that helps, which is
    the opposite direction for >= than for <=."""
    req = _req(limit="100 mm", operator=">=")
    assert req.evaluate(99 * ureg.mm)[0] == "violated"
    assert req.evaluate(99 * ureg.mm, parse_tolerance("2 mm", req.limit))[0] == "within_tolerance"
