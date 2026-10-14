"""The FreeCAD adapter, against a stand-in worker.

No FreeCAD runs here. `freecad_fake.FakeWorker` answers protocol 1 with canned
values, so what is tested is everything the CLIENT decides: which object a
label means, which number comes back with which unit, when a mass may be
computed, and that every way the worker can be missing or wrong ends as a gap
-- never as a crash, and never as a plausible number.

`test_a_rotated_part_keeps_its_stated_length` is the one that says why the
adapter exists: the bounding box of a rotated box is not its length, and the
named parameter still is.
"""


import httpx
import pytest

from freecad_fake import ALUMINIUM, DIMENSIONLESS, FakeDocument, FakeWorker, cube_document, mm, q
from sysmlcad.adapters import CadAdapter, Unsupported, WritableAdapter
from sysmlcad.adapters.freecad_adapter import (
    URL_ENV,
    FreeCadAdapter,
    decode_quantity,
    encode_quantity,
)
from sysmlcad.units import ureg

CUBE = "projects/demo/cube.FCStd"


@pytest.fixture
def root(tmp_path):
    """A repository root with a document in it -- its bytes are the state."""
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    (tmp_path / CUBE).write_bytes(b"PK fake FCStd, revision 1")
    return tmp_path


@pytest.fixture
def worker():
    return FakeWorker(documents={CUBE: cube_document()})


@pytest.fixture
def adapter(root, worker):
    return FreeCadAdapter(url="http://freecad.test", transport=worker.transport(), root=root)


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------

def test_it_is_a_cad_adapter_and_a_writable_one(adapter):
    assert isinstance(adapter, CadAdapter)
    assert isinstance(adapter, WritableAdapter)


@pytest.mark.parametrize("wire, expected", [
    (mm(100.0), 100 * ureg.mm),
    (q(6e6, [3, 0, 0, 0, 0, 0, 0, 0]), 6e6 * ureg.mm**3),
    (q(0.75, [0, 1, 0, 0, 0, 0, 0, 0]), 0.75 * ureg.kg),
    (ALUMINIUM["density"], 2.70 * ureg.g / ureg.cm**3),
    (q(45.0, [0, 0, 0, 0, 0, 0, 0, 1]), 45 * ureg.degree),
    (q(3.0, DIMENSIONLESS), 3 * ureg.dimensionless),
])
def test_a_quantity_is_rebuilt_from_its_signature(wire, expected):
    """FreeCAD's internal units, never a unit NAME -- which depends on the
    user's unit schema and would make the same document read differently on
    two machines."""
    decoded = decode_quantity(wire)
    assert decoded.dimensionality == expected.dimensionality
    assert decoded.to(expected.units).magnitude == pytest.approx(expected.magnitude)


@pytest.mark.parametrize("quantity", [
    100 * ureg.mm, 0.12 * ureg.m, 1.5 * ureg.kg, 2.7 * ureg.g / ureg.cm**3, 30 * ureg.degree,
])
def test_a_limit_survives_the_round_trip(quantity):
    back = decode_quantity(encode_quantity(quantity))
    assert back.to(quantity.units).magnitude == pytest.approx(quantity.magnitude)


@pytest.mark.parametrize("wire", [
    {"value": "100", "unit": [1, 0, 0, 0, 0, 0, 0, 0]},
    {"value": float("nan"), "unit": [1, 0, 0, 0, 0, 0, 0, 0]},
    {"value": 100.0, "unit": [1, 0, 0]},
    {"value": 100.0, "unit": "mm"},
    {"value": True, "unit": [1, 0, 0, 0, 0, 0, 0, 0]},
    100.0,
])
def test_a_malformed_quantity_is_refused(wire):
    with pytest.raises(Unsupported):
        decode_quantity(wire)


# --------------------------------------------------------------------------
# Addressing
# --------------------------------------------------------------------------

def test_an_object_is_addressed_by_label_and_measured_by_name(root):
    """The label is what a designer wrote and a mapping names; the internal
    name is what FreeCAD guarantees unique. The client resolves one to the
    other, so the worker never has to guess."""
    document = cube_document()
    document.objects[0] = {**document.objects[0], "label": "Housing (rev A)", "name": "Box001"}
    document.measures = {k.replace("Box|", "Box001|"): v for k, v in document.measures.items()}
    worker = FakeWorker(documents={CUBE: document})
    adapter = FreeCadAdapter(url="http://f.test", transport=worker.transport(), root=root)

    assert adapter.measure(f"{CUBE}#Housing (rev A)", "bbox_size", {"axis": "X"}) == 100 * ureg.mm
    path, body = worker.requests[-1]
    assert path == "/v1/measure" and body["object"] == "Box001"


def test_a_single_root_is_the_whole_document(adapter):
    assert adapter.measure(CUBE, "bbox_size", {"axis": "Z"}) == 300 * ureg.mm


def test_several_roots_need_a_label(root):
    document = cube_document()
    document.objects.append({**document.objects[0], "label": "Lid", "name": "Box001"})
    adapter = FreeCadAdapter(
        url="http://f.test", transport=FakeWorker({CUBE: document}).transport(), root=root
    )
    with pytest.raises(Unsupported, match="2 root objects"):
        adapter.measure(CUBE, "volume")


def test_an_ambiguous_label_is_refused_rather_than_guessed(root):
    document = cube_document()
    document.objects.append({**document.objects[0], "name": "Box001"})
    adapter = FreeCadAdapter(
        url="http://f.test", transport=FakeWorker({CUBE: document}).transport(), root=root
    )
    with pytest.raises(Unsupported, match="ambiguous"):
        adapter.measure(f"{CUBE}#Box", "volume")


def test_a_missing_label_names_what_is_available(adapter):
    with pytest.raises(Unsupported, match="Available: Box"):
        adapter.measure(f"{CUBE}#Lid", "volume")


def test_a_missing_document_is_a_gap_before_any_request(adapter, worker):
    with pytest.raises(Unsupported, match="no FreeCAD document"):
        adapter.measure("projects/demo/other.FCStd", "volume")
    assert worker.requests == []


# --------------------------------------------------------------------------
# What a document gives that a STEP export does not
# --------------------------------------------------------------------------

def test_a_named_parameter_is_the_stated_dimension(adapter):
    assert adapter.measure(CUBE, "parameter", {"name": "Params.Length"}) == 100 * ureg.mm
    assert adapter.parameter(CUBE, "Box.Length") == 100 * ureg.mm
    assert adapter.parameter(CUBE, "Params.Nothing") is None


def test_a_missing_parameter_is_a_gap_that_lists_the_others(adapter):
    with pytest.raises(Unsupported, match="Params.Length"):
        adapter.measure(CUBE, "parameter", {"name": "Params.Depth"})


def test_a_rotated_part_keeps_its_stated_length(root):
    """The case the adapter exists for. Turned 45 degrees about Z, the box's
    bounding box along X is ~212 mm and a length check against it fails; the
    parameter it was built from still says 100 mm."""
    document = cube_document()
    document.measures = {}
    document.answer("Box", "bbox_size", {"axis": "X"}, mm(212.13))
    adapter = FreeCadAdapter(
        url="http://f.test", transport=FakeWorker({CUBE: document}).transport(), root=root
    )
    assert adapter.measure(CUBE, "bbox_size", {"axis": "X"}) > 120 * ureg.mm
    assert adapter.measure(CUBE, "parameter", {"name": "Params.Length"}) == 100 * ureg.mm


def test_mass_comes_from_the_documents_material(adapter):
    """6e6 mm^3 of aluminium at 2.70 g/cm^3 = 16.2 kg, with nothing written
    into the mapping."""
    assert adapter.measure(CUBE, "mass").to(ureg.kg).magnitude == pytest.approx(16.2)
    assert adapter.material(CUBE).name == "Aluminum"


def test_a_density_override_still_works_for_what_if_studies(adapter):
    assert adapter.measure(CUBE, "mass", {"density_g_per_cm3": 1.36}).magnitude == pytest.approx(8.16)


def test_no_material_means_no_mass_rather_than_a_guessed_one(root):
    document = cube_document()
    document.objects[0] = {**document.objects[0], "material": None}
    adapter = FreeCadAdapter(
        url="http://f.test", transport=FakeWorker({CUBE: document}).transport(), root=root
    )
    with pytest.raises(Unsupported, match="no material"):
        adapter.measure(CUBE, "mass")


def test_a_zero_density_is_no_density(root):
    """FreeCAD's default material reads 0 -- a part weighing nothing would pass
    every mass limit."""
    document = cube_document()
    document.objects[0] = {**document.objects[0],
                           "material": {"name": "Default", "density": q(0.0, [-3, 1, 0, 0, 0, 0, 0, 0])}}
    adapter = FreeCadAdapter(
        url="http://f.test", transport=FakeWorker({CUBE: document}).transport(), root=root
    )
    with pytest.raises(Unsupported, match="no material with a density"):
        adapter.measure(CUBE, "mass")


def test_an_object_that_does_not_recompute_is_not_measured(root):
    """A failed recompute leaves the last good shape in the document. Measuring
    it would report the design as it was, not as it is."""
    document = cube_document()
    document.objects[0] = {**document.objects[0], "error": "Sketch is over-constrained"}
    worker = FakeWorker({CUBE: document})
    adapter = FreeCadAdapter(url="http://f.test", transport=worker.transport(), root=root)
    with pytest.raises(Unsupported, match="could not recompute"):
        adapter.measure(CUBE, "bbox_size", {"axis": "X"})
    assert "/v1/measure" not in [path for path, _ in worker.requests]


# --------------------------------------------------------------------------
# Every way the worker can be missing or wrong is a gap
# --------------------------------------------------------------------------

def test_no_worker_configured_is_a_gap_that_names_the_setting(root, monkeypatch):
    monkeypatch.delenv(URL_ENV, raising=False)
    with pytest.raises(Unsupported, match=URL_ENV):
        FreeCadAdapter(root=root).measure(CUBE, "volume")


def test_an_unreachable_worker_is_a_gap(root):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)
    adapter = FreeCadAdapter(url="http://f.test", transport=httpx.MockTransport(refuse), root=root)
    with pytest.raises(Unsupported, match="not reachable"):
        adapter.measure(CUBE, "volume")


def test_a_failing_worker_is_a_gap(root):
    adapter = FreeCadAdapter(
        url="http://f.test", root=root,
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="Traceback ...")),
    )
    with pytest.raises(Unsupported, match="HTTP 500"):
        adapter.measure(CUBE, "volume")


def test_another_protocol_version_is_refused(root):
    worker = FakeWorker({CUBE: cube_document()}, protocol=2)
    adapter = FreeCadAdapter(url="http://f.test", transport=worker.transport(), root=root)
    with pytest.raises(Unsupported, match="protocol 2"):
        adapter.measure(CUBE, "volume")


def test_a_worker_answer_of_the_wrong_dimension_is_refused(root):
    """A worker that reported a volume in mm would be a worker bug, and the
    number would otherwise become a verdict."""
    document = cube_document().answer("Box", "volume", {}, mm(6e6))
    adapter = FreeCadAdapter(
        url="http://f.test", transport=FakeWorker({CUBE: document}).transport(), root=root
    )
    with pytest.raises(Unsupported, match="expected dimension"):
        adapter.measure(CUBE, "volume")


def test_the_workers_own_refusal_is_passed_on(adapter):
    with pytest.raises(Unsupported, match="cannot measure cylinder_radius"):
        adapter.measure(CUBE, "cylinder_radius")


@pytest.mark.parametrize("method, args", [
    ("bbox_size", {"axes": "X"}),
    ("bbox_size", {"axis": "Q"}),
    ("parameter", {}),
    ("cylinder_radius", {"kind": "slot"}),
    ("mass", {"density_g_per_cm3": 0}),
    ("length", {}),
])
def test_a_bad_mapping_entry_is_one_gap_and_sends_no_measure(adapter, worker, method, args):
    with pytest.raises(Unsupported):
        adapter.measure(CUBE, method, args)
    assert "/v1/measure" not in [path for path, _ in worker.requests]


# --------------------------------------------------------------------------
# State and catalogue
# --------------------------------------------------------------------------

def test_the_state_is_the_documents_bytes(root, worker):
    first = FreeCadAdapter(url="http://f.test", transport=worker.transport(), root=root)
    first.measure(CUBE, "volume")
    (root / CUBE).write_bytes(b"PK fake FCStd, revision 2")
    second = FreeCadAdapter(url="http://f.test", transport=worker.transport(), root=root)
    second.measure(CUBE, "volume")
    assert first.state_id() != second.state_id()


def test_the_catalogue_lists_parameters_and_only_possible_methods(adapter):
    [target] = adapter.catalog([CUBE])
    assert target.reference == CUBE            # one root: addressed bare
    assert target.name == "Box"
    assert target.parameters["Params.Length"] == 100 * ureg.mm
    assert "parameter" in target.methods and "mass" in target.methods
    assert "material Aluminum" in target.note


def test_an_assembly_lists_its_components_by_label(root):
    document = FakeDocument(objects=[
        {"label": "Gearbox", "name": "Part", "type": "App::Part", "parent": None, "has_shape": True},
        {"label": "Housing", "name": "Body", "type": "PartDesign::Body", "parent": "Gearbox",
         "has_shape": True, "material": ALUMINIUM},
        {"label": "Cover", "name": "Body001", "type": "PartDesign::Body", "parent": "Gearbox",
         "has_shape": True},
    ])
    adapter = FreeCadAdapter(
        url="http://f.test", transport=FakeWorker({CUBE: document}).transport(), root=root
    )
    targets = {t.name: t for t in adapter.catalog([CUBE])}
    assert targets["Gearbox"].kind == "assembly" and targets["Gearbox"].depth == 0
    assert targets["Housing"].reference == f"{CUBE}#Housing" and targets["Housing"].depth == 1
    assert "mass" in targets["Housing"].methods
    assert "mass" not in targets["Cover"].methods          # no material, no mass
    assert "parameter" not in targets["Cover"].methods     # no parameters at all


def test_an_unreadable_document_is_listed_not_dropped(root, monkeypatch):
    """A stopped FreeCAD container must read as exactly that -- a document
    that exists and cannot be measured -- not as a missing file."""
    monkeypatch.delenv(URL_ENV, raising=False)
    [target] = FreeCadAdapter(root=root).catalog([CUBE])
    assert not target.addressable
    assert URL_ENV in target.note


# --------------------------------------------------------------------------
# Writing limits
# --------------------------------------------------------------------------

def test_a_dry_run_writes_nothing(adapter, worker):
    changes = adapter.write_limits(CUBE, "SysML", {"MaxLength": 100 * ureg.mm})
    assert [(c.alias, c.old, c.new) for c in changes] == [("MaxLength", None, 100 * ureg.mm)]
    assert worker.documents[CUBE].sheets == {}


def test_apply_writes_and_a_second_sync_has_nothing_to_say(adapter, worker):
    adapter.write_limits(CUBE, "SysML", {"MaxLength": 100 * ureg.mm}, apply=True)
    assert "MaxLength" in worker.documents[CUBE].sheets["SysML"]["cells"]
    assert adapter.write_limits(CUBE, "SysML", {"MaxLength": 100 * ureg.mm}) == []


def test_a_changed_limit_reports_old_and_new(adapter):
    adapter.write_limits(CUBE, "SysML", {"MaxLength": 100 * ureg.mm}, apply=True)
    [change] = adapter.write_limits(CUBE, "SysML", {"MaxLength": 0.12 * ureg.m})
    assert change.old == 100 * ureg.mm
    assert change.new.to(ureg.mm).magnitude == pytest.approx(120)


def test_a_sheet_somebody_else_owns_is_never_written(adapter, worker):
    worker.documents[CUBE].sheets["Params"] = {"managed": False, "cells": {}}
    with pytest.raises(Unsupported, match="not managed"):
        adapter.write_limits(CUBE, "Params", {"Length": 1 * ureg.mm}, apply=True)


def test_limits_go_into_a_document_not_an_object(adapter):
    with pytest.raises(Unsupported, match="into a document"):
        adapter.write_limits(f"{CUBE}#Box", "SysML", {"MaxLength": 100 * ureg.mm})
