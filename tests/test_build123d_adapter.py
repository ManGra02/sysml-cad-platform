"""The build123d adapter, and the hole that `module#Component` closes.

Until components were addressable, an assembly script could only be measured as
a whole. A component had to go through the STEP export instead -- which carries
no material, so its mass needed `density_g_per_cm3` written into
`mapping.yaml`.

That is the failure these tests exist for, and it is worth stating precisely
because it passes every gate: a density is a *fact about the part*, and
`mapping.yaml` holds the *correspondence between two models*. Putting it there
made the mapping a third source of truth that neither model owns. Change the
material in the script and the check keeps using the old density -- reporting a
confident, wrong mass that nothing catches, because the dimension is right, the
measurement is possible, the entry is unique and the magnitude is plausible.

`test_a_component_inherits_the_script_material` is the one that would fail if
somebody reintroduced the override.
"""

import pytest

from sysmlcad.adapters import Unsupported
from sysmlcad.adapters.build123d_adapter import Build123dAdapter, _snake
from sysmlcad.adapters.step_adapter import StepAdapter
from sysmlcad.units import ureg


@pytest.fixture
def adapter():
    return Build123dAdapter()


# --------------------------------------------------------------------------
# Addressing
# --------------------------------------------------------------------------

def test_a_whole_module_is_still_addressed_by_name(adapter):
    """The plain form keeps working: `build()` is the assembly."""
    assert adapter.measure("gearbox", "bbox_size", {"axis": "Z"}) == 46.0 * ureg.mm


def test_a_component_is_addressed_after_the_hash(adapter):
    """`gearbox#Housing` reaches `build_housing()`. The assembly is 46 mm tall
    because the cover sits on top; the housing alone is 40."""
    assert adapter.measure("gearbox#Housing", "bbox_size", {"axis": "Z"}) == 40.0 * ureg.mm
    assert adapter.measure("gearbox#Cover", "bbox_size", {"axis": "Z"}) == 6.0 * ureg.mm


def test_the_component_name_is_read_case_insensitively(adapter):
    """`#Housing` and `#housing` are the same component. The builder convention
    is `build_<snake_case>`, and a mapping should not fail on capitalisation."""
    upper = adapter.measure("gearbox#Housing", "volume")
    lower = adapter.measure("gearbox#housing", "volume")
    assert upper == lower


def test_snake_case_handles_the_conventions_in_use():
    assert _snake("Housing") == "housing"
    assert _snake("GearRing") == "gear_ring"
    assert _snake("Gear Ring") == "gear_ring"


def test_an_unknown_component_names_what_exists(adapter):
    """A refusal that lists the alternatives, because the component names are
    the addresses and there is no other way to learn them."""
    with pytest.raises(Unsupported) as excinfo:
        adapter.measure("gearbox#Flywheel", "volume")

    message = str(excinfo.value)
    assert "Flywheel" in message
    assert "build_flywheel" in message
    assert "Housing" in message and "Cover" in message


def test_a_module_without_build_is_refused(adapter):
    with pytest.raises(Unsupported, match="has no build"):
        adapter.measure("export_fixtures", "volume")


# --------------------------------------------------------------------------
# The point of the exercise
# --------------------------------------------------------------------------

def test_a_component_inherits_the_script_material(adapter):
    """The reason `#` exists.

    The component's mass comes from the material the script declares, so no
    density is written into the mapping -- and nothing goes stale when the
    material changes.
    """
    material = adapter.material("gearbox#Housing")

    assert material is not None
    assert material.name == "AlSi10Mg"
    assert material.density == 2.70 * ureg.g / ureg.cm**3
    # And the mass is computable with no arguments at all.
    assert adapter.measure("gearbox#Housing", "mass").units == ureg.kg


def test_changing_the_material_changes_the_mass(adapter, monkeypatch):
    """The property the override destroyed. With the density in the script, a
    material change propagates; frozen in the mapping, it would not."""
    import gearbox

    aluminium = Build123dAdapter().measure("gearbox#Housing", "mass")
    monkeypatch.setattr(gearbox, "DENSITY_G_PER_CM3", 1.36)
    plastic = Build123dAdapter().measure("gearbox#Housing", "mass")

    assert plastic < aluminium
    assert plastic.magnitude == pytest.approx(aluminium.magnitude * 1.36 / 2.70, rel=1e-9)


def test_the_committed_mapping_carries_no_density(adapter):
    """A density in `mapping.yaml` is a fact about a part in the file that holds
    the correspondence between two models. There is now a route that does not
    need one, so there should be none left."""
    from sysmlcad.mapping import load_mapping
    from sysmlcad.project import list_projects, load_project

    for name in list_projects():
        for entry in load_mapping(load_project(name).mapping_path).attributes:
            assert "density_g_per_cm3" not in (entry.args or {}), (
                f"{name}: {entry.sysml_part}.{entry.attribute} freezes a density in the mapping"
            )


# --------------------------------------------------------------------------
# Consistency with the other adapter, and with itself
# --------------------------------------------------------------------------

def test_both_adapters_measure_the_same_component():
    """Script and STEP export agree on a component, exactly as they do on a
    whole part. The routes differ in what they know about material, not in what
    they measure."""
    script = Build123dAdapter()
    step = StepAdapter()

    for method, args in [("volume", {}), ("bbox_size", {"axis": "X"}), ("face_count", {})]:
        from_script = script.measure("gearbox#Housing", method, args)
        from_file = step.measure("fixtures/step/gearbox.step#Housing", method, args)
        assert from_script.magnitude == pytest.approx(from_file.magnitude, rel=1e-9), method


def test_the_components_add_up_to_the_assembly(adapter):
    """A weak check on the addressing: if `#Housing` silently returned the whole
    assembly, this would not hold."""
    housing = adapter.measure("gearbox#Housing", "volume")
    cover = adapter.measure("gearbox#Cover", "volume")
    assembly = adapter.measure("gearbox", "volume")

    assert (housing + cover).magnitude == pytest.approx(assembly.magnitude, rel=1e-9)


def test_state_id_is_per_module_not_per_component(adapter):
    """Two components of one script share a design state. Hashing the source
    once per reference would claim otherwise -- and would change the digest
    recorded in every past run for no reason."""
    adapter.measure("gearbox#Housing", "volume")
    one = adapter.state_id()
    adapter.measure("gearbox#Cover", "volume")

    assert adapter.state_id() == one


def test_the_reference_digest_is_unchanged():
    """The motor housing's `cad state` appears in the documented reference run.
    Component addressing must not have moved it."""
    assert Build123dAdapter(["motor_housing"]).state_id() == "bdaee4cff5d3ddfa"


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

def test_the_catalogue_offers_the_components(adapter):
    references = {t.reference for t in adapter.catalog(["gearbox"])}

    assert "gearbox" in references
    assert "gearbox#Housing" in references
    assert "gearbox#Cover" in references


def test_a_component_target_offers_mass(adapter):
    """Because the script declares a material. This is what makes the mapping
    proposable without inventing a density."""
    housing = next(t for t in adapter.catalog(["gearbox"]) if t.reference == "gearbox#Housing")

    assert "mass" in housing.methods
    assert housing.kind == "part"
    assert "AlSi10Mg" in housing.note
