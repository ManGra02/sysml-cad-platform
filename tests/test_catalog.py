"""The structural excerpt of both models.

The SysML half runs against `fixtures/elements.json`, a captured API response,
so it needs no server -- the same approach `test_extract.py` takes. The CAD half
runs against the committed STEP fixtures and the CAD scripts.

What these tests are really protecting is the input to everything downstream: a
catalogue that quietly loses an attribute, or claims a measurement an adapter
cannot make, produces mapping proposals that are wrong in a way no later stage
can detect.
"""

import pytest
from build123d import Box, BuildPart, Compound, Unit, export_step

from sysmlcad.adapters.step_adapter import StepAdapter
from sysmlcad.catalog import (
    CatalogAttribute,
    cad_catalog,
    load_catalog,
    load_elements,
    sysml_catalog,
)
from sysmlcad.project import load_project
from sysmlcad.units import ureg

MOTOR = load_project("motor_housing")
GEARBOX = load_project("gearbox")


@pytest.fixture(scope="module")
def parts():
    """The motor housing project's parts. One project, one capture."""
    elements, _source = load_elements(MOTOR)
    return sysml_catalog(elements)


@pytest.fixture(scope="module")
def gearbox_parts():
    elements, _source = load_elements(GEARBOX)
    return sysml_catalog(elements)


@pytest.fixture(scope="module")
def housing(parts):
    return next(p for p in parts if p.name == "motorHousing")


@pytest.fixture(scope="module")
def targets():
    return cad_catalog()


# --------------------------------------------------------------------------
# The SysML side
# --------------------------------------------------------------------------

def test_finds_the_part_and_its_definition(housing):
    assert housing.definition == "Housing"
    assert housing.element_id


def test_a_project_sees_only_its_own_model(parts, gearbox_parts):
    """The inverse of what this test used to assert. The catalogue once merged
    every capture, so a proposer saw two unrelated `Housing`s side by side and
    could -- did -- map one model's attributes onto the other's part. A project
    is one model; the other one is not a neighbour, it is absent."""
    assert {p.name for p in parts} == {"motorHousing"}
    assert {p.name for p in gearbox_parts} == {"housing", "cover", "gearbox"}


def test_the_two_projects_share_no_parts(parts, gearbox_parts):
    assert {p.name for p in parts}.isdisjoint({p.name for p in gearbox_parts})


def test_lists_the_attributes_of_the_definition(housing):
    assert [a.name for a in housing.attributes] == ["length", "mass"]


def test_each_attribute_appears_once(parts):
    """A membership names its member under two keys. Reading both without
    de-duplicating produced every attribute twice -- which would have doubled
    every proposal built on this catalogue."""
    for part in parts:
        names = [a.name for a in part.attributes]
        assert len(names) == len(set(names)), f"{part.name} has duplicates"


def test_a_nested_part_carries_its_own_attributes(gearbox_parts):
    """`gearbox` owns `housing` and `cover`, and each definition's attributes
    must stay with it -- collecting the whole reachable subgraph would give the
    assembly its components' attributes as well."""
    gearbox = next(p for p in gearbox_parts if p.name == "gearbox")
    assert [a.name for a in gearbox.attributes] == ["mass"]


def test_the_type_name_carries_the_dimension(housing):
    by_name = {a.name: a for a in housing.attributes}
    assert by_name["length"].type_name == "LengthValue"
    assert by_name["length"].dimensionality == ureg.mm.dimensionality
    assert by_name["mass"].dimensionality == ureg.kg.dimensionality


def test_an_unknown_value_type_yields_no_dimension():
    """"We cannot check this" and "this is dimensionless" are different answers.
    A guess here would let a wrong mapping pass the dimension gate."""
    unknown = CatalogAttribute(name="stiffness", element_id="x", type_name="SpringRate")
    assert unknown.unit is None
    assert unknown.dimensionality is None


def test_library_parts_are_not_catalogued():
    library = [
        {"@id": "1", "@type": "PartUsage", "declaredName": "somethingFromISQ",
         "isLibraryElement": True},
    ]
    assert sysml_catalog(library) == ()


# --------------------------------------------------------------------------
# The CAD side
# --------------------------------------------------------------------------

def test_cad_scripts_are_catalogued_with_their_parameters(targets):
    housing = next(t for t in targets if t.reference == "motor_housing")
    assert housing.kind == "module"
    assert housing.parameters["LENGTH_MM"] == 118.0 * ureg.mm
    assert "AlSi10Mg" in housing.note


def test_step_nodes_are_catalogued_by_their_reference_string(targets):
    """The reference is exactly what a mapping entry's `cad_object:` takes, so a
    proposal can be copied rather than reconstructed."""
    references = [t.reference for t in targets]
    assert "fixtures/step/gearbox.step#Housing" in references
    assert "fixtures/step/gearbox.step#Cover" in references


def test_the_step_assembly_is_marked_as_one(targets):
    gearbox = next(t for t in targets if t.reference == "fixtures/step/gearbox.step")
    assert gearbox.kind == "assembly"
    assert next(
        t for t in targets if t.reference == "fixtures/step/gearbox.step#Housing"
    ).kind == "part"


def test_mass_is_not_offered_where_it_could_only_produce_a_gap(targets):
    """The STEP fixtures carry no material. Offering `mass` on them would
    propose a mapping whose only possible outcome is a gap -- so the catalogue
    leaves it out, while the script that declares a density keeps it."""
    step_node = next(
        t for t in targets if t.reference == "fixtures/step/gearbox.step#Housing"
    )
    assert "mass" not in step_node.methods
    assert "bbox_size" in step_node.methods

    script = next(t for t in targets if t.reference == "motor_housing")
    assert "mass" in script.methods


def test_a_step_file_advertises_no_parameters(targets):
    """Not an omission: a baked file has none, and a proposer must see that
    rather than infer it."""
    for target in targets:
        if target.reference.endswith(".step") or ".step#" in target.reference:
            assert target.parameters == {}


def test_an_ambiguous_node_is_listed_but_not_addressable(tmp_path):
    """The catalogue is a proposer's candidate space, so a node that cannot be
    addressed by name must not look like a candidate. It is still listed --
    "this exists but you cannot point at it" is what a human needs to see to go
    and rename it."""
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

    targets = StepAdapter().catalog([str(path)])
    brackets = [t for t in targets if t.name == "Bracket"]
    assert len(brackets) == 2
    assert all(not t.addressable for t in brackets)
    assert all("ambiguous" in t.note for t in brackets)

    frame = next(t for t in targets if t.name == "Frame")
    assert frame.addressable


# --------------------------------------------------------------------------
# Both sides at once
# --------------------------------------------------------------------------

def test_the_catalogue_can_be_looked_up_by_name():
    catalog = load_catalog(MOTOR)
    assert catalog.part("motorHousing") is not None
    assert catalog.attribute("motorHousing", "length").type_name == "LengthValue"
    assert catalog.attribute("motorHousing", "nonsense") is None
    assert catalog.target("motor_housing") is not None
    assert catalog.source.endswith("elements.json")
