"""ModelSnapshot.neighbours() and the agent tool sysml_neighbours -- the context of one part.

The CAD Reuse Assistant cannot judge a part on its own: a motor mount depends on the motor
and the frame it connects, and on the requirements of the assemblies above it.
"""

import json
from types import SimpleNamespace

import pytest_asyncio

from app.ai.tools import sysml_tools
from app.sysml.config import SysmlConfig
from app.sysml.demo import SAMPLES_DIR, build_ebike, load_sample
from app.sysml.parser import parse_elements
from app.sysml.service import SysmlService
from fake_flexo import FakeFlexo


def ebike():
    return parse_elements(build_ebike().commit_payload(), version="c1")


def drone():
    return parse_elements(json.loads((SAMPLES_DIR / "drone_demo.json").read_text(encoding="utf-8")))


# -- The snapshot method (offline) ---------------------------------------


def test_motor_kennt_rahmen_typ_und_anforderungen():
    snap = ebike()
    motor = snap.find("motor", kind="part")[0]
    n = snap.neighbours(motor.id)

    assert n["version"] == "c1"
    assert n["element"]["name"] == "motor" and n["element"]["type"] == "Motor"
    mass = next(a for a in n["element"]["attributes"] if a["name"] == "mass")
    assert (mass["value"], mass["unit"], mass["value_si"], mass["unit_si"]) == (9.8, "kg", 9.8, "kg")

    assert n["parent"]["name"] == "driveUnit"
    assert n["children"] == []                       # leaf part

    # connected through the interface usage "motorMount" -- with the frame's values
    assert [(c["name"], c["via"], c["via_kind"]) for c in n["connected"]] == [("frame", "motorMount", "interface")]
    frame = n["connected"][0]
    assert any(a["name"] == "holeSpacing" and a["value_si"] == 0.08 for a in frame["attributes"])

    # its own requirement, and the mass budget of the drive unit above it
    assert [r["req_id"] for r in n["requirements"]] == ["REQ-MOT-004"]
    assert [(r["req_id"], r["from"]) for r in n["inherited_requirements"]] == [("REQ-DU-001", "driveUnit")]
    assert n["allocations"] == []


def test_verbindung_wird_von_beiden_seiten_gesehen():
    snap = ebike()
    frame = snap.find("frame", kind="part")[0]
    n = snap.neighbours(frame.id)
    assert [c["name"] for c in n["connected"]] == ["motor"]
    assert {c["name"] for c in n["children"]} == {"mountingBracket", "cableGuide"}
    assert [r["req_id"] for r in n["requirements"]] == ["REQ-FR-002"]


def test_drohne_batterie_und_geerbte_anforderung():
    snap = drone()
    battery = snap.find("battery", kind="part")[0]
    n = snap.neighbours(battery.id)
    assert [(c["name"], c["via"]) for c in n["connected"]] == [("flightController", "batteryConnector")]
    assert [r["req_id"] for r in n["requirements"]] == ["REQ-DR-002"]
    # the whole quadcopter must stay under 1.5 kg -- that limits the battery too
    assert ("REQ-DR-001", "quadcopter") in [(r["req_id"], r["from"]) for r in n["inherited_requirements"]]


def test_unbekannte_id():
    assert ebike().neighbours("does-not-exist") is None


# -- The agent tool, against the Flexo stand-in --------------------------


@pytest_asyncio.fixture
async def sysml():
    fake = FakeFlexo()
    url = await fake.start()
    service = SysmlService(SysmlConfig(api_url=url, timeout_s=5))
    project = await service.client.create_project("EBike Demo")
    await service.client.post_commit(project["@id"], load_sample("ebike")["change"], description="seed")
    yield service
    await service.stop()
    await fake.stop()


def tool(service, name):
    tools = {t.name: t for t in sysml_tools(SimpleNamespace(sysml=service))}
    return tools[name]


async def test_tool_mit_namen(sysml):
    result = json.loads(await tool(sysml, "sysml_neighbours").ainvoke({"project": "EBike Demo", "element": "motor"}))
    assert result["element"]["name"] == "motor"
    assert result["connected"][0]["name"] == "frame"
    assert result["requirements"][0]["req_id"] == "REQ-MOT-004"


async def test_tool_mit_id(sysml):
    snap = await sysml.snapshot("EBike Demo")
    battery = snap.find("battery", kind="part")[0]
    result = json.loads(await tool(sysml, "sysml_neighbours").ainvoke({"project": "EBike Demo", "element": battery.id}))
    assert result["element"]["id"] == battery.id
    assert result["parent"]["name"] == "driveUnit"


async def test_tool_meldet_fehler_statt_zu_crashen(sysml):
    result = json.loads(await tool(sysml, "sysml_neighbours").ainvoke({"project": "EBike Demo", "element": "warpDrive"}))
    assert result["error"]["code"] == "element_not_found"
    result = json.loads(await tool(sysml, "sysml_neighbours").ainvoke({"project": "Nope", "element": "motor"}))
    assert result["error"]["code"] == "sysml_project_not_found"
