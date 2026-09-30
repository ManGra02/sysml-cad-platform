"""M7: project registry -- selection, delivery of CAD events, the modules' CAD access.

Against the mock bridge, without FreeCAD.
"""

import json

import aiohttp
import pytest_asyncio

import pytest

from app.projects.base import CadError, ProjectModule, Ref
from app.projects.bds import BdsModule
from app.projects.mcr import McrModule
from conftest import BrowserClient, running_backend, wait_for


class RecordingModule(ProjectModule):
    """Records all hooks -- and writes to CAD itself on request."""

    id = "rec"
    title = "Recorder"
    calls = []

    def __init__(self):
        self.events = []
        self.own = []

    def register_routes(self, router):
        @router.get("/events")
        async def events():
            return self.events

        @router.post("/write")
        async def write():
            return await self.ctx.cad.patch("Doc", "Box", {"Length": "5 mm"})

        @router.get("/doc")
        async def doc():
            return await self.ctx.cad.documents()

    async def on_activate(self):
        RecordingModule.calls.append(("activate", self.id))

    async def on_deactivate(self):
        RecordingModule.calls.append(("deactivate", self.id))

    async def on_cad_event(self, event):
        self.events.append(event)
        self.own.append(self.ctx.cad.is_own(event))


class BrokenModule(ProjectModule):
    id = "broken"
    title = "Broken"

    async def on_cad_event(self, event):
        raise RuntimeError("A module error must not stop the platform")


MODULES = [BdsModule, McrModule, RecordingModule, BrokenModule]


@pytest_asyncio.fixture
async def platform(handshake):
    RecordingModule.calls = []
    async with running_backend(project_modules=MODULES) as handle:
        yield handle


def module(platform, module_id):
    return platform.state.registry.modules[module_id]


# -- Registry and switching --------------------------------------------


async def test_standardmodule_sind_registriert(backend):
    code, body = await backend.get("/api/projects")
    assert code == 200
    assert [p["id"] for p in body["projects"]] == ["bds", "mcr"]
    assert body["active"] is None
    assert all(p["title"] and p["description"] and p["icon"] for p in body["projects"])


async def test_aktivieren(platform):
    code, body = await platform.post("/api/projects/bds/activate")
    assert code == 200
    assert body["active"] == "bds"
    assert [p["id"] for p in body["projects"] if p["active"]] == ["bds"]


async def test_unbekanntes_projekt_404(platform):
    code, body = await platform.post("/api/projects/doesnotexist/activate")
    assert code == 404
    assert body["error"]["code"] == "project_not_found"


async def test_umschalten_ruft_die_haken(platform):
    await platform.post("/api/projects/rec/activate")
    await platform.post("/api/projects/bds/activate")
    assert RecordingModule.calls == [("activate", "rec"), ("deactivate", "rec")]


async def test_nochmal_aktivieren_ist_kein_neustart(platform):
    await platform.post("/api/projects/rec/activate")
    await platform.post("/api/projects/rec/activate")
    assert RecordingModule.calls == [("activate", "rec")]


async def test_alle_tabs_erfahren_den_wechsel(platform):
    browser = await BrowserClient(platform.url).connect()
    try:
        await platform.post("/api/projects/mcr/activate")
        await wait_for(lambda: any(f.get("type") == "project.activated" for f in browser.frames))
        frame = [f for f in browser.frames if f.get("type") == "project.activated"][0]
        assert frame["id"] == "mcr"
    finally:
        await browser.close()


async def test_hello_nennt_das_aktive_projekt(platform):
    await platform.post("/api/projects/bds/activate")
    browser = await BrowserClient(platform.url).connect()
    try:
        await wait_for(lambda: browser.frames)
        assert browser.frames[0]["project"] == "bds"
    finally:
        await browser.close()


async def test_wahl_ueberlebt_den_neustart(handshake, state_dir):
    """--reload restarts the backend on every code change."""
    RecordingModule.calls = []
    async with running_backend(project_modules=MODULES) as first:
        await first.post("/api/projects/rec/activate")
    RecordingModule.calls = []
    async with running_backend(project_modules=MODULES) as second:
        _, body = await second.get("/api/projects")
        assert body["active"] == "rec"
        assert RecordingModule.calls == [("activate", "rec")]  # module becomes active again
    assert json.loads((state_dir / "state.json").read_text())["active"] == "rec"


async def test_kaputte_zustandsdatei_ist_kein_absturz(handshake, state_dir):
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text("{broken")
    async with running_backend(project_modules=MODULES) as handle:
        _, body = await handle.get("/api/projects")
        assert body["active"] is None


# -- Module routes ------------------------------------------------------


async def test_modulrouten_unter_eigenem_praefix(platform):
    code, body = await platform.get("/api/projects/bds/info")
    assert code == 200
    assert body["id"] == "bds" and body["stub"] is True


async def test_modulrouten_sind_abgesichert(platform):
    """The Origin check also applies to the modules' routes."""
    async with aiohttp.ClientSession() as session:
        async with session.get(platform.url + "/api/projects/bds/info",
                               headers={"Origin": "https://evil.example"}) as response:
            assert response.status == 403


# -- Events from FreeCAD -----------------------------------------------


async def test_nur_das_aktive_projekt_bekommt_ereignisse(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    await platform.post("/api/projects/rec/activate")
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "Box", "props": ["Length"],
                        "origin": "freecad:user"}])
    await wait_for(lambda: module(platform, "rec").events)
    assert module(platform, "rec").events[0]["obj"] == "Box"

    await platform.post("/api/projects/bds/activate")
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "Cylinder", "origin": "freecad:user"}])
    await wait_for(lambda: module(platform, "bds").events_seen == 1)
    assert len(module(platform, "rec").events) == 1


async def test_ohne_aktives_projekt_wird_nichts_zugestellt(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "Box", "origin": "freecad:user"}])
    await platform.post("/api/projects/rec/activate")
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "Second", "origin": "freecad:user"}])
    await wait_for(lambda: module(platform, "rec").events)
    assert [e["obj"] for e in module(platform, "rec").events] == ["Second"]


async def test_modulfehler_stoppt_die_zustellung_nicht(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    await platform.post("/api/projects/broken/activate")
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "A", "origin": "freecad:user"}])
    await platform.post("/api/projects/rec/activate")
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "B", "origin": "freecad:user"}])
    await wait_for(lambda: module(platform, "rec").events)
    code, _ = await platform.get("/api/status")
    assert code == 200


async def test_stub_meldet_sich_beim_browser(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    await platform.post("/api/projects/bds/activate")
    browser = await BrowserClient(platform.url).connect()
    try:
        await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "Box", "origin": "freecad:user"}])
        await wait_for(lambda: any(f.get("type") == "bds.cad_seen" for f in browser.frames))
        _, info = await platform.get("/api/projects/bds/info")
        assert info["eventsSeen"] == 1 and info["recent"][0]["obj"] == "Box"
    finally:
        await browser.close()


# -- The modules' CAD access -------------------------------------------


async def test_modul_liest_ueber_das_backend(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    code, body = await platform.get("/api/projects/rec/doc")
    assert code == 200
    assert body["active"] == "Doc"


async def test_modul_schreibt_mit_eigener_request_id(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    code, body = await platform.post("/api/projects/rec/write")
    assert code == 200
    assert body["received"] == {"Length": "5 mm"}
    assert body["request_id"].startswith("rec:")


async def test_modul_erkennt_das_echo_seiner_eigenen_aenderung(bridge, platform):
    """Foundation of any bidirectional synchronization: otherwise ping-pong."""
    await wait_for(lambda: platform.state.bridge.state == "ok")
    await platform.post("/api/projects/rec/activate")
    _, body = await platform.post("/api/projects/rec/write")
    await bridge.push([
        {"type": "cad.changed", "doc": "Doc", "obj": "Box", "origin": "bridge:" + body["request_id"]},
        {"type": "cad.changed", "doc": "Doc", "obj": "Box", "origin": "freecad:user"},
        {"type": "cad.changed", "doc": "Doc", "obj": "Box", "origin": "bridge:other-browser"},
    ])
    await wait_for(lambda: len(module(platform, "rec").own) == 3)
    assert module(platform, "rec").own == [True, False, False]


async def test_cad_fehler_kommen_typisiert_beim_modul_an(platform):
    """Without a bridge: CadError instead of a raw exception."""
    from app.projects.base import CadError

    try:
        await module(platform, "rec").ctx.cad.documents()
    except CadError as exc:
        assert exc.status == 503 and exc.code == "bridge_unconfigured"
    else:
        raise AssertionError("CadError expected")



# -- M8: transactions via ctx.cad --------------------------------------


async def test_transaction_sendet_genau_einen_vorgang(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    cad = module(platform, "rec").ctx.cad
    async with cad.transaction("Doc", "BDS: create motor") as tx:
        m = tx.create("Part::Box", name="Motor", group="Drive", props={"Length": "40 mm"})
        tx.add_property(m, "App::PropertyString", "SysMLId", value="elem-1", group="SysML")
        tx.set_cells("Params", {"A1": "40 mm"}, aliases={"A1": "motor_length"})
        tx.set_expression(m, "Length", "Params.motor_length")
        tx.patch("Cylinder", {"Radius": "5 mm"}, if_match=3)
    assert len(bridge.operations) == 1
    sent = bridge.operations[0]
    assert sent["request_id"].startswith("rec:")
    ops = sent["body"]["ops"]
    assert [op["op"] for op in ops] == ["create", "add_property", "set_cells", "set_expression", "patch"]
    assert ops[1]["obj"] == ops[3]["obj"] == "$" + ops[0]["as"]
    assert ops[4]["if_match"] == 3
    assert sent["body"]["name"] == "BDS: create motor"
    assert isinstance(m, Ref) and tx.result.name(m) == "Motor"


async def test_exception_im_block_sendet_nichts(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    cad = module(platform, "rec").ctx.cad
    with pytest.raises(RuntimeError):
        async with cad.transaction("Doc") as tx:
            tx.create("Part::Box")
            raise RuntimeError("Abort in own code")
    assert bridge.operations == []
    assert tx.result is None


async def test_fehler_nennt_die_operation(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    cad = module(platform, "rec").ctx.cad
    with pytest.raises(CadError) as caught:
        async with cad.transaction("Doc") as tx:
            tx.create("Part::Box", name="ok")
            tx.create("Part::Box", name="fail")
    assert caught.value.failed_op == 1
    assert caught.value.status == 400


async def test_kurzformen(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    cad = module(platform, "rec").ctx.cad
    assert await cad.create("Doc", "Part::Sphere", "Sphere") == "Sphere"
    await cad.delete("Doc", "Sphere", force=True)
    assert bridge.operations[-1]["body"]["ops"] == [{"op": "delete", "obj": "Sphere", "force": True}]
    cells = await cad.cells("Doc", "Params", "A1:B2")
    assert cells["range"] == "A1:B2" and cells["cells"]["A1"]["alias"] == "length"


async def test_echo_eines_vorgangs_ist_eigen(bridge, platform):
    await wait_for(lambda: platform.state.bridge.state == "ok")
    await platform.post("/api/projects/rec/activate")
    rec = module(platform, "rec")
    await rec.ctx.cad.create("Doc", "Part::Box", "New")
    request_id = bridge.operations[-1]["request_id"]
    await bridge.push([{"type": "cad.created", "doc": "Doc", "obj": "New", "origin": "bridge:" + request_id}])
    await wait_for(lambda: rec.own)
    assert rec.own == [True]


def test_objekt_muss_name_oder_ref_sein():
    from app.projects.base import Transaction

    tx = Transaction(None, "Doc")
    with pytest.raises(TypeError):
        tx.delete(42)
