"""`cylinder_radius`, on shapes built right here.

The method answers "how big is THE bore", so the tests that matter are the
ones where there is no single bore: none at all, several, or a fillet that is
a cylinder too. Each of those has a plausible number lying around -- the first
cylinder found -- and returning it would be a confident answer about the
wrong feature. They must come back as `Unsupported`, which a run reports as a
gap.
"""

import pytest
from build123d import Axis, Box, Cylinder, Location, Rotation, fillet

from sysmlcad.adapters import Unsupported
from sysmlcad.adapters.measurements import cylinder_radius
from sysmlcad.units import ureg


def _plate_with_bore(radius=8.0):
    return Box(90, 60, 40) - Cylinder(radius, 40)


def _tube():
    """Outer radius 5, inner radius 3: one boss, one hole, one axis."""
    return Cylinder(5, 20) - Cylinder(3, 20)


def test_a_bore_is_measured():
    assert cylinder_radius(_plate_with_bore()) == 8.0 * ureg.mm


def test_the_radius_comes_from_the_geometry():
    """Not from a parameter: change the bore and the measurement follows."""
    assert cylinder_radius(_plate_with_bore(radius=6.5)) == 6.5 * ureg.mm


def test_no_cylinder_is_a_gap():
    with pytest.raises(Unsupported, match="no cylindrical face"):
        cylinder_radius(Box(10, 10, 10))


def test_two_cylinders_are_an_error_not_a_choice():
    with pytest.raises(Unsupported, match="2 cylindrical features"):
        cylinder_radius(_tube())


def test_kind_tells_a_bore_from_a_shaft():
    assert cylinder_radius(_tube(), kind="hole") == 3.0 * ureg.mm
    assert cylinder_radius(_tube(), kind="boss") == 5.0 * ureg.mm


def test_a_fillet_is_a_cylinder_too():
    """Four rounded edges are four bosses of the same radius on four different
    axis lines -- four features, so even the agreeing radius is refused. The
    bore inside them is still reachable by saying `hole`."""
    rounded = fillet(Box(30, 30, 10).edges().filter_by(Axis.Z), 2) - Cylinder(4, 10)
    with pytest.raises(Unsupported, match="5 cylindrical features"):
        cylinder_radius(rounded)
    with pytest.raises(Unsupported, match="4 cylindrical features"):
        cylinder_radius(rounded, kind="boss")
    assert cylinder_radius(rounded, kind="hole") == 4.0 * ureg.mm


def test_axis_tells_two_bores_apart():
    cross = (
        Box(40, 40, 40)
        - Cylinder(3, 40)
        - Location((0, 0, 0)) * Rotation(0, 90, 0) * Cylinder(5, 40)
    )
    with pytest.raises(Unsupported, match="2 cylindrical features"):
        cylinder_radius(cross, kind="hole")
    assert cylinder_radius(cross, axis="Z") == 3.0 * ureg.mm
    assert cylinder_radius(cross, axis="x") == 5.0 * ureg.mm


def test_one_bore_through_two_bodies_is_one_feature():
    """Coaxial and equal, as in the gearbox: housing and cover share the bore."""
    stacked = _plate_with_bore() + Location((0, 0, 23)) * (Box(90, 60, 6) - Cylinder(8, 6))
    assert cylinder_radius(stacked) == 8.0 * ureg.mm


def test_two_parallel_bores_are_two_features():
    """Parallel is not coaxial: same radius, different lines."""
    twin = Box(60, 20, 10) - Location((-15, 0, 0)) * Cylinder(4, 10) \
        - Location((15, 0, 0)) * Cylinder(4, 10)
    with pytest.raises(Unsupported, match="2 cylindrical features"):
        cylinder_radius(twin)


@pytest.mark.parametrize("args", [{"kind": "inner"}, {"axis": "Q"}])
def test_a_bad_argument_is_unsupported(args):
    with pytest.raises(Unsupported):
        cylinder_radius(_plate_with_bore(), **args)
