"""The STEP adapter: reading a CAD file the project did not author.

Two of these tests earn their keep more than the others:

* `test_both_adapters_measure_the_same` is what pays for keeping the
  measurement vocabulary in two places. Adding STEP support was meant to be an
  add-on, so `Build123dAdapter` was left untouched rather than refactored to
  share code. This test enforces the invariant a shared module would have
  guaranteed: measure the same geometry through both paths, get the same
  answer.

* `test_a_part_authored_in_inches_reads_back_in_millimetres` guards the one
  failure that would be worse than a crash. A silent factor of 25.4 in a
  verification tool produces confident, wrong verdicts.
"""

from pathlib import Path

import pytest
from build123d import Box, BuildPart, Compound, Unit, export_step

from sysmlcad.adapters import Unsupported
from sysmlcad.adapters.build123d_adapter import Build123dAdapter
from sysmlcad.adapters.step_adapter import StepAdapter
from sysmlcad.units import ureg

STEP_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "step"
HOUSING = str(STEP_DIR / "motor_housing.step")
INCH = str(STEP_DIR / "motor_housing_inch.step")
GEARBOX = str(STEP_DIR / "gearbox.step")

pytestmark = pytest.mark.skipif(
    not (STEP_DIR / "motor_housing.step").is_file(),
    reason="STEP fixtures missing -- run `make step-fixtures`",
)


@pytest.fixture
def adapter():
    return StepAdapter()


# --------------------------------------------------------------------------
# The two that matter most
# --------------------------------------------------------------------------

def test_both_adapters_measure_the_same(adapter):
    """Same geometry, one measured from the script, one from the STEP export."""
    native = Build123dAdapter()

    for method, args in [
        ("volume", {}),
        ("bbox_size", {"axis": "X"}),
        ("bbox_size", {"axis": "Z"}),
        ("face_count", {}),
        ("cylinder_radius", {"kind": "hole"}),
    ]:
        from_script = native.measure("motor_housing", method, args)
        from_file = adapter.measure(HOUSING, method, args)
        assert from_script.units == from_file.units, method
        assert from_script.magnitude == pytest.approx(from_file.magnitude, rel=1e-9), (
            f"{method}{args}: script {from_script} vs STEP {from_file}"
        )


def test_a_part_authored_in_inches_reads_back_in_millimetres(adapter):
    """The file declares inches; OCCT must convert. A factor of 25.4 slipping
    through here would produce confident, wrong verdicts."""
    in_mm = adapter.measure(HOUSING, "bbox_size", {"axis": "X"})
    in_inch = adapter.measure(INCH, "bbox_size", {"axis": "X"})
    assert str(in_inch.units) == "millimeter"
    assert in_inch.magnitude == pytest.approx(in_mm.magnitude, rel=1e-6)


# --------------------------------------------------------------------------
# Addressing
# --------------------------------------------------------------------------

def test_a_named_node_of_an_assembly_is_addressable(adapter):
    housing = adapter.measure(f"{GEARBOX}#Housing", "volume")
    cover = adapter.measure(f"{GEARBOX}#Cover", "volume")
    assert housing.magnitude > cover.magnitude > 0


def test_the_assembly_aggregates_its_children(adapter):
    total = adapter.measure(GEARBOX, "volume")
    housing = adapter.measure(f"{GEARBOX}#Housing", "volume")
    cover = adapter.measure(f"{GEARBOX}#Cover", "volume")
    assert total.magnitude == pytest.approx((housing + cover).magnitude, rel=1e-9)


def test_assembly_bounding_box_spans_both_parts(adapter):
    height = adapter.measure(GEARBOX, "bbox_size", {"axis": "Z"})
    housing = adapter.measure(f"{GEARBOX}#Housing", "bbox_size", {"axis": "Z"})
    assert height.magnitude > housing.magnitude


def test_a_missing_node_names_what_is_available(adapter):
    with pytest.raises(Unsupported) as exc:
        adapter.measure(f"{GEARBOX}#Flywheel", "volume")
    assert "Flywheel" in str(exc.value)
    assert "Housing" in str(exc.value), "the error should list the real names"


def test_a_missing_file_is_a_gap_not_a_crash(adapter):
    with pytest.raises(Unsupported):
        adapter.measure("fixtures/step/nope.step", "volume")


def test_an_ambiguous_name_is_refused_rather_than_guessed(adapter, tmp_path):
    """Two nodes, one name. Picking the first would be the same class of bug as
    substituting a value: a plausible number from the wrong object."""
    with BuildPart() as small:
        Box(10, 10, 10)
    with BuildPart() as large:
        Box(20, 20, 20)

    first, second = small.part, large.part
    first.label = second.label = "Bracket"
    assembly = Compound(children=[first, second])
    assembly.label = "Frame"

    path = tmp_path / "ambiguous.step"
    export_step(assembly, str(path), unit=Unit.MM)

    with pytest.raises(Unsupported) as exc:
        adapter.measure(f"{path}#Bracket", "volume")
    assert "ambiguous" in str(exc.value).lower()


# --------------------------------------------------------------------------
# What STEP cannot do -- reported, never faked
# --------------------------------------------------------------------------

def test_a_step_file_has_no_named_parameters(adapter):
    """Not a missing feature: it is what the format is. Named parameters need a
    live CAD document, which is the FreeCAD adapter's job."""
    assert adapter.parameter(HOUSING, "LENGTH_MM") is None
    assert adapter.parameter(HOUSING, "anything") is None


def test_no_material_means_no_mass_rather_than_a_guessed_one(adapter):
    assert adapter.material(HOUSING) is None
    with pytest.raises(Unsupported) as exc:
        adapter.measure(HOUSING, "mass")
    assert "material" in str(exc.value).lower()


def test_a_density_override_makes_mass_computable(adapter):
    """The replacement-part study: what if this were a different material?"""
    mass = adapter.measure(HOUSING, "mass", {"density_g_per_cm3": 2.70})
    assert mass.to("kg").magnitude == pytest.approx(0.7429, rel=1e-3)

    steel = adapter.measure(HOUSING, "mass", {"density_g_per_cm3": 7.85})
    assert steel.magnitude > mass.magnitude


def test_an_unknown_method_is_a_gap(adapter):
    with pytest.raises(Unsupported):
        adapter.measure(HOUSING, "wall_thickness")


def test_a_bad_axis_is_refused(adapter):
    with pytest.raises(Unsupported):
        adapter.measure(HOUSING, "bbox_size", {"axis": "Q"})


def test_an_unexpected_argument_is_refused(adapter):
    """A TypeError here would take the whole run down with one mapping typo."""
    with pytest.raises(Unsupported, match="axsi"):
        adapter.measure(HOUSING, "bbox_size", {"axis": "X", "axsi": "Y"})
    with pytest.raises(Unsupported):
        adapter.measure(HOUSING, "volume", {"axis": "X"})


def test_a_density_override_must_be_a_positive_number(adapter):
    with pytest.raises(Unsupported, match="positive"):
        adapter.measure(HOUSING, "mass", {"density_g_per_cm3": 0})


# --------------------------------------------------------------------------
# Several root shapes
# --------------------------------------------------------------------------

def _two_roots(path):
    """A file with two free shapes and no assembly above them -- common in
    exports, and not something build123d's `export_step` writes."""
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    doc = TDocStd_Document(TCollection_ExtendedString("two-roots"))
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    for name, size in (("Shaft", 10), ("Key", 5)):
        with BuildPart() as part:
            Box(size, size, size)
        label = tool.AddShape(part.part.wrapped, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.Transfer(doc, STEPControl_AsIs)
    writer.Write(str(path))
    return str(path)


def test_several_roots_are_each_addressable_and_the_bare_file_is_not(adapter, tmp_path):
    path = _two_roots(tmp_path / "loose.step")

    with pytest.raises(Unsupported, match="root shapes"):
        adapter.measure(path, "volume")
    assert adapter.measure(f"{path}#Key", "volume").magnitude == pytest.approx(125.0)


def test_the_catalogue_lists_several_roots_by_name(adapter, tmp_path):
    """It used to raise on the first multi-root file it met: each root was
    listed under the bare path, which `_node` refuses."""
    path = _two_roots(tmp_path / "loose.step")
    references = {t.reference for t in adapter.catalog([path])}
    assert references == {f"{path}#Shaft", f"{path}#Key"}


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def test_state_id_follows_the_file_contents(tmp_path):
    """Same file name, different bytes: a different design state.

    Comparing two differently NAMED files would pass on the name alone -- the
    digest includes it -- and prove nothing about the content."""
    renamed = tmp_path / "motor_housing.step"
    renamed.write_bytes(Path(GEARBOX).read_bytes())

    one = StepAdapter()
    one.measure(HOUSING, "volume")
    other = StepAdapter()
    other.measure(str(renamed), "volume")
    assert one.state_id() != other.state_id()


def test_state_id_is_stable_for_the_same_file():
    a, b = StepAdapter(), StepAdapter()
    a.measure(HOUSING, "volume")
    b.measure(HOUSING, "volume")
    assert a.state_id() == b.state_id()


def test_tree_reports_the_assembly_structure(adapter):
    nodes = adapter.tree(GEARBOX)
    names = {node.name for _, node in nodes}
    assert {"Gearbox", "Housing", "Cover"} <= names
    depths = {node.name: depth for depth, node in nodes}
    assert depths["Housing"] > depths["Gearbox"], "children sit below the assembly"
