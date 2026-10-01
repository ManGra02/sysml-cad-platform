"""SysML adapter: parsing, units, the service against a Flexo stand-in, /api/sysml/*, ctx.sysml.

Without Docker and without FreeCAD: parsing runs on data/examples/sysml/, the rest
against fake_flexo.FakeFlexo, which speaks the SysML v2 API with Flexo's semantics.
"""

import json
import struct

import pytest
import pytest_asyncio

from app.sysml.client import SysmlError
from app.sysml.config import SysmlConfig
from app.sysml.demo import SAMPLES_DIR, build_ebike, load_sample
from app.sysml.expressions import clean_float
from app.sysml.parser import parse_elements
from app.sysml.service import SysmlService
from app.sysml.units import convert, to_si
from conftest import free_port, running_backend
from fake_flexo import FakeFlexo

SAMPLE = SAMPLES_DIR / "PartsTreeRedefinition.json"


# -- Parsing (offline) ---------------------------------------------------


def test_flexo_testmodell_wird_verstanden():
    """Flexo's own test model: vehicle1.mass = 1750 [kg]."""
    snap = parse_elements(json.loads(SAMPLE.read_text(encoding="utf-8")), project_id="p", version="c1")
    assert {"vehicle1", "frontAxleAssembly", "rearWheel", "frontWheel_2"} <= {p.name for p in snap.parts()}
    vehicle = snap.find("vehicle1")[0]
    mass = next(a for a in snap.attributes_of(vehicle.id) if a.name == "mass")
    assert (mass.value, mass.unit, mass.value_si, mass.expression) == (1750, "kg", 1750.0, "1750 [kg]")
    axle = snap.find("frontAxleAssembly")[0]
    assert axle.parent_id == vehicle.id
    assert any(snap.element(t).name == "AxleAssembly" for t in axle.type_ids)
    assert not [e for e in snap.elements if e.name == "kilogram"]   # library elements are filtered


def test_ebike_demo():
    snap = parse_elements(build_ebike().commit_payload())
    motor = snap.find("motor", kind="part")[0]
    attrs = {a.name: a for a in snap.attributes_of(motor.id)}
    assert (attrs["maxMass"].value, attrs["maxMass"].unit) == (10.0, "kg")
    assert (attrs["ratedPower"].value_si, attrs["ratedPower"].unit_si) == (250.0, "W")
    battery = snap.find("battery", kind="part")[0]
    length = next(a for a in snap.attributes_of(battery.id) if a.name == "envelopeLength")
    assert (length.value_si, length.unit_si) == (0.36, "m")
    req = next(r for r in snap.requirements() if r.extra["req_id"] == "REQ-MOT-004")
    assert "10 kg" in req.extra["text"]
    assert any(r.kind == "satisfies" and r.source_id == motor.id and r.target_id == req.id for r in snap.relations)
    assert any(r.kind == "connects" for r in snap.relations)
    assert {p.name for p in snap.leaf_parts()} == {"battery", "controller", "coolingSystem", "motor",
                                                   "sensorMount", "cableGuide", "mountingBracket", "wheelset"}
    assert "<SatisfyRequirementUsage>" not in snap.tree_text()


def test_ebike_datei_entspricht_dem_generator():
    """data/examples/sysml/ebike_demo.json is the generated model, byte for byte in content."""
    on_disk = json.loads((SAMPLES_DIR / "ebike_demo.json").read_text(encoding="utf-8"))
    assert on_disk["change"] == load_sample("ebike")["change"]


def test_einheiten():
    assert to_si(80, "mm") == (0.08, "m")
    assert to_si(700, "mm") == (0.7, "m")
    assert convert(11200, "g", "kg") == 11.2
    assert to_si(5, "furlong") == (None, None)
    with pytest.raises(ValueError):
        convert(1, "kg", "m")


def test_float32_rauschen_von_flexo():
    """Flexo returns decimals through a 32-bit float: 9.8 -> 9.800000190734863."""
    f32 = struct.unpack("f", struct.pack("f", 9.8))[0]
    assert f32 != 9.8 and clean_float(f32) == 9.8
    assert clean_float(3.14159265358979) == 3.14159265358979


# -- The service against the Flexo stand-in -----------------------------


@pytest_asyncio.fixture
async def flexo():
    fake = FakeFlexo()
    url = await fake.start()
    fake.url = url
    yield fake
    await fake.stop()


@pytest_asyncio.fixture
async def sysml(flexo):
    service = SysmlService(SysmlConfig(api_url=flexo.url, timeout_s=5))
    yield service
    await service.stop()


async def seed(service, model="ebike", name="EBike Demo"):
    project = await service.client.create_project(name)
    commit = await service.client.post_commit(project["@id"], load_sample(model)["change"], description="seed")
    return project["@id"], commit["@id"]


async def test_snapshot_ueber_http(sysml):
    pid, cid = await seed(sysml)
    snap = await sysml.snapshot("EBike Demo")            # by name, head of the default branch
    assert (snap.version, snap.project_id) == (cid, pid)
    assert len(snap.parts()) == 11
    assert await sysml.snapshot(pid, commit_id=cid) is snap   # cached per commit


async def test_zurueckschreiben_und_diff(sysml):
    pid, c1 = await seed(sysml)
    snap = await sysml.snapshot(pid)
    motor = snap.find("motor", kind="part")[0]
    mass = next(a for a in snap.attributes_of(motor.id) if a.name == "mass")
    c2 = (await sysml.write_attribute_value(pid, mass.id, 11200, unit="g"))["@id"]   # CAD reports grams
    new = await sysml.snapshot(pid)
    assert new.version == c2
    assert (new.attribute(mass.id).value, new.attribute(mass.id).unit) == (11.2, "kg")
    diff = await sysml.diff(pid, c1, c2)
    assert diff["summary"]["attributes_changed"] == 1
    assert diff["attributes"]["changed"][0]["to"] == "11.2 [kg]"


async def test_diff_findet_neues_teil(sysml):
    pid, c1 = await seed(sysml)
    drive_unit = (await sysml.snapshot(pid)).find("driveUnit")[0]
    change = [{"identity": {"@id": "new-part-1"},
               "payload": {"@type": "PartUsage", "declaredName": "thermalPad", "owner": {"@id": drive_unit.id}}}]
    c2 = (await sysml.commit_changes(pid, change, "add thermal pad"))["@id"]
    assert (await sysml.diff(pid, c1, c2))["summary"]["parts_added"] == ["thermalPad"]


async def test_fehler_haben_codes(sysml):
    with pytest.raises(SysmlError) as info:
        await sysml.snapshot("does-not-exist")
    assert (info.value.status, info.value.code) == (404, "sysml_project_not_found")
    await seed(sysml)
    with pytest.raises(SysmlError) as info:
        await sysml.write_attribute_value("EBike Demo", "nope", 1.0)
    assert info.value.code == "sysml_attribute_not_found"


async def test_nicht_erreichbar_ist_ein_normaler_zustand():
    service = SysmlService(SysmlConfig(api_url="http://127.0.0.1:%d" % free_port(), timeout_s=2))
    try:
        status = await service.status()
        assert status["reachable"] is False and status["code"] == "sysml_unreachable"
    finally:
        await service.stop()


async def test_verbindungsaufbau_haengt_ist_auch_nicht_erreichbar():
    """Windows: a closed port is not refused at once but retried ~2 s. An address that
    never answers reproduces that everywhere -- it must count as unreachable, not slow."""
    service = SysmlService(SysmlConfig(api_url="http://10.255.255.1:8083", timeout_s=2))
    try:
        status = await service.status()
        assert status["reachable"] is False and status["code"] == "sysml_unreachable"
    finally:
        await service.stop()


# -- /api/sysml/* and ctx.sysml in the real backend ----------------------


async def test_api_routen(handshake, flexo):
    service = SysmlService(SysmlConfig(api_url=flexo.url, timeout_s=5))
    pid, cid = await seed(service)
    async with running_backend(sysml_service=service) as backend:
        code, status = await backend.get("/api/sysml/status")
        assert code == 200 and status["reachable"] is True and status["projects"] == 1

        code, body = await backend.get("/api/sysml/projects/%s/parts" % pid, params={"leafOnly": "true"})
        assert code == 200 and body["version"] == cid
        assert "coolingSystem" in {p["name"] for p in body["parts"]}

        code, body = await backend.get("/api/sysml/projects/%s/requirements" % pid)
        assert len(body["requirements"]) == 3 and len(body["satisfies"]) == 3

        code, body = await backend.get("/api/sysml/projects/nope/parts")
        assert code == 404 and body["error"]["code"] == "sysml_project_not_found"

        _, parts = await backend.get("/api/sysml/projects/%s/parts" % pid)
        motor = next(p for p in parts["parts"] if p["name"] == "motor")
        _, element = await backend.get("/api/sysml/projects/%s/elements/%s" % (pid, motor["id"]))
        mass = next(a for a in element["attributes"] if a["name"] == "mass")
        async with backend.http.put(backend.url + "/api/sysml/projects/%s/attributes/%s/value" % (pid, mass["id"]),
                                    json={"value": 10.4, "unit": "kg"}) as response:
            assert response.status == 200
        async with backend.http.get(backend.url + "/api/sysml/projects/EBike%20Demo/tree") as response:
            assert "mass = 10.4 [kg]" in await response.text()


async def test_api_ohne_flexo(handshake):
    service = SysmlService(SysmlConfig(api_url="http://127.0.0.1:%d" % free_port(), timeout_s=2))
    async with running_backend(sysml_service=service) as backend:
        code, status = await backend.get("/api/sysml/status")
        assert code == 200 and status["reachable"] is False
        code, body = await backend.get("/api/sysml/projects")
        assert code == 503 and body["error"]["code"] == "sysml_unreachable"
        code, _ = await backend.get("/api/status")   # the rest of the platform is unaffected
        assert code == 200


async def test_module_bekommen_ctx_sysml(handshake, flexo):
    service = SysmlService(SysmlConfig(api_url=flexo.url, timeout_s=5))
    async with running_backend(sysml_service=service) as backend:
        modules = backend.state.registry.modules
        assert modules and all(m.ctx.sysml is service for m in modules.values())
        assert backend.state.sysml is service
