"""BDS (bidirectional-sync, ported): extraction, CAD adapter, gates, verification, proposals,
confirmation, limit sync and scoring -- without Flexo, FreeCAD or a model.

The SysML side is the PoC's captured models (data/examples/sysml/bds/), the CAD side
fake_cad.FakeCad in the bridge's response shapes.
"""

import json
import math
from pathlib import Path

import pytest
import pytest_asyncio
from conftest import running_backend
from fake_cad import ALUMINIUM, FakeCad, cube, gearbox, prop
from fake_flexo import FakeFlexo
from fake_ollama import FakeOllama, answer

from app.ai import AiConfig, AiService
from app.projects.bds import confirm as confirm_mod
from app.projects.bds import limits, verify
from app.projects.bds.adapters import AdapterPool, Unsupported
from app.projects.bds.bridge_adapter import (
    MARKER,
    BridgeAdapter,
    decode_quantity,
    freecad_text,
)
from app.projects.bds.catalog import build_catalog
from app.projects.bds.extract import by_key, extract
from app.projects.bds.gates import check_mapping, check_proposal
from app.projects.bds.mapping import load_mapping, parse_mapping
from app.projects.bds.model import (
    BadTolerance,
    DimensionMismatch,
    Requirement,
    parse_tolerance,
)
from app.projects.bds.proposals import Proposal, add, load_proposals, save_proposals
from app.projects.bds.propose import DifflibProposer
from app.projects.bds.propose import run as propose_run
from app.projects.bds.propose_ai import LlmProposer, json_schema, parse_answer, render_catalog
from app.projects.bds.score import GoldEntry, score
from app.projects.bds.units import ureg
from app.projects.bds.workspace import (
    BdsError,
    list_workspaces,
    load_workspace,
    save_workspace,
)
from app.sysml.config import SysmlConfig
from app.sysml.service import SysmlService

MODELS = Path(__file__).resolve().parents[2] / "data" / "examples" / "sysml" / "bds"


def elements(model):
    return json.loads((MODELS / ("%s.json" % model)).read_text(encoding="utf-8"))


GEARBOX_MAPPING = """\
version: 2
parts:
  - sysml_part: housing
    adapter: freecad
    cad_object: Gearbox#Body
    status: confirmed
  - sysml_part: cover
    adapter: freecad
    cad_object: Gearbox#Housing-is-not-this
    status: proposed
  - sysml_part: gearbox
    adapter: freecad
    cad_object: Gearbox
    status: confirmed
attributes:
  - sysml_part: housing
    attribute: length
    requirement: MaxHousingLength
    method: bbox_size
    args: {axis: X}
    status: confirmed
  - sysml_part: housing
    attribute: boreRadius
    requirement: MinBoreRadius
    method: cylinder_radius
    args: {kind: hole}
    status: confirmed
  - sysml_part: gearbox
    attribute: mass
    requirement: MaxAssemblyMass
    method: mass
    status: confirmed
  - sysml_part: cover
    attribute: thickness
    requirement: MaxCoverThickness
    method: bbox_size
    args: {axis: Z}
    status: confirmed
"""


@pytest.fixture
def workspace_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BDS_DATA_DIR", str(tmp_path / "bds"))
    return tmp_path / "bds"


async def gearbox_session(cad=None, mapping_text=GEARBOX_MAPPING):
    cad = cad or FakeCad(gearbox())
    adapter = await BridgeAdapter.load(cad, ["Gearbox"])
    model = elements("gearbox")
    requirements, skipped = extract(model)
    return {
        "adapter": adapter,
        "pool": AdapterPool({"freecad": adapter}),
        "catalog": build_catalog(model, adapter),
        "requirements": requirements,
        "skipped": skipped,
        "by_key": by_key(requirements),
        "mapping": parse_mapping(mapping_text),
    }


# -- Extraction (SysML) -------------------------------------------------------

def test_extract_findet_die_requirements_des_getriebes():
    requirements, skipped = extract(elements("gearbox"))
    found = {(r.requirement_id, r.subject, r.operator, format(r.limit, "~P")) for r in requirements}
    assert skipped == []
    assert found == {
        ("MaxAssemblyMass", "gearbox", "<=", "1.5 kg"),
        ("MinBoreRadius", "housing", ">=", "8 mm"),
        ("MaxHousingLength", "housing", "<=", "95 mm"),
        # `satisfy ... by gearbox.cover`: the feature chain's LAST link is the subject
        ("MaxCoverThickness", "cover", "<=", "8 mm"),
    }


def test_extract_auf_vereinfachtem_demo_modell_findet_nichts():
    """The platform's ModelBuilder demos are a simplified subset -- not BDS input."""
    from app.sysml.demo import load_sample
    from app.sysml.parser import normalise_elements

    requirements, _ = extract(normalise_elements(load_sample("ebike")))
    assert requirements == []


def test_catalog_kennt_teile_attribute_und_verschachtelung():
    parts = {p.name: p for p in build_catalog(elements("gearbox"), FakeAdapterless()).parts}
    assert parts["housing"].container == "gearbox"
    assert parts["gearbox"].container == ""
    assert [a.name for a in parts["cover"].attributes] == ["length", "width", "thickness", "boreRadius", "mass"]
    assert str(parts["cover"].attributes[0].dimensionality) == "[length]"


class FakeAdapterless:
    def catalog(self):
        return []


# -- Model --------------------------------------------------------------------

def requirement(operator="<=", limit=100):
    return Requirement("MaxLength", "e1", "box", "length", operator, limit * ureg.mm)


def test_drei_wertiges_urteil():
    assert requirement().evaluate(99 * ureg.mm)[0] == "compliant"
    assert requirement().evaluate(101 * ureg.mm)[0] == "violated"
    assert requirement().evaluate(101 * ureg.mm, parse_tolerance("2 mm", 100 * ureg.mm))[0] == "within_tolerance"
    assert requirement(">=").evaluate(99 * ureg.mm, parse_tolerance("2%", 100 * ureg.mm))[0] == "within_tolerance"


def test_falsche_dimension_ist_kein_urteil():
    with pytest.raises(DimensionMismatch):
        requirement().evaluate(1 * ureg.kg)
    with pytest.raises(BadTolerance):
        parse_tolerance("5 kg", 100 * ureg.mm)


# -- CAD through the bridge ----------------------------------------------------

async def test_katalog_der_cad_seite():
    adapter = await BridgeAdapter.load(FakeCad(gearbox()), ["Gearbox"])
    targets = {t.reference: t for t in adapter.catalog()}
    # One root (the App::Part) -> addressed by the document name; features and
    # sketches are consumed by their bodies and not listed.
    assert sorted(targets) == ["Gearbox", "Gearbox#Body", "Gearbox#Body001"]
    assert targets["Gearbox"].kind == "assembly"
    assert targets["Gearbox#Body"].container == "Gearbox"
    assert targets["Gearbox#Body"].name == "Housing"
    assert "component of Gearbox" in targets["Gearbox#Body"].note
    # Feature parameters belong to their body; spreadsheet aliases to everyone.
    assert set(targets["Gearbox#Body"].parameters) == {"Pad.Length", "Params.HousingLength", "Params.CoverCount"}
    assert set(targets["Gearbox#Body001"].parameters) == {"Pad001.Length", "Params.HousingLength",
                                                          "Params.CoverCount"}
    assert "Pad.Offset" not in targets["Gearbox#Body"].parameters        # an exact zero says nothing


async def test_messungen():
    adapter = await BridgeAdapter.load(FakeCad(gearbox()), ["Gearbox"])
    assert adapter.measure("Gearbox#Body", "bbox_size", {"axis": "X"}) == 90 * ureg.mm   # tight box
    assert adapter.measure("Gearbox#Housing", "bbox_size", {"axis": "z"}) == 40 * ureg.mm  # by label
    assert adapter.measure("Gearbox#Body", "face_count") == 11 * ureg.dimensionless
    assert adapter.measure("Gearbox#Body", "cylinder_radius", {"kind": "hole"}) == 8 * ureg.mm
    assert adapter.measure("Gearbox#Body", "parameter", {"name": "Pad.Length"}) == 40 * ureg.mm
    housing = adapter.measure("Gearbox#Body", "mass")
    assert math.isclose(housing.to("kg").magnitude, (90 * 60 * 40 - math.pi * 64 * 40) * 2.7e-6)
    # The App::Part has no material of its own: it weighs what its bodies weigh.
    total = adapter.measure("Gearbox", "mass").to("kg").magnitude
    assert math.isclose(total, (90 * 60 * 46 - math.pi * 64 * 46) * 2.7e-6)


async def test_mehrdeutiges_und_unmessbares_wird_zur_luecke():
    adapter = await BridgeAdapter.load(FakeCad(gearbox(), cube()), ["Gearbox", "Cube", "Closed"])
    with pytest.raises(Unsupported, match="2 cylindrical features"):
        adapter.measure("Gearbox#Body", "cylinder_radius")          # the bore and a fillet
    with pytest.raises(Unsupported, match="no material"):
        adapter.measure("Cube", "mass")                             # FreeCAD's default material
    with pytest.raises(Unsupported, match="not open"):
        adapter.measure("Closed#Body", "volume")
    with pytest.raises(Unsupported, match="no measurable object"):
        adapter.measure("Gearbox#Pad", "volume")
    with pytest.raises(Unsupported, match="unexpected keyword"):
        adapter.measure("Gearbox#Body", "volume", {"axis": "X"})
    closed = next(t for t in adapter.catalog() if t.reference == "Closed")
    assert closed.methods == () and "not open" in closed.note


async def test_body_ohne_form_faellt_aus_der_baugruppe():
    """An empty Body is not listed -- and the assembly's mass is not tripped up by it."""
    doc = gearbox()
    doc.add("Body002", "PartDesign::Body", "Empty", properties=[prop("Shape", None, status="derived")],
            geometry={"null": True, "shapeType": None})
    doc.objects["Part"]["children"].append("Body002")
    adapter = await BridgeAdapter.load(FakeCad(doc), ["Gearbox"])
    assert "Gearbox#Body002" not in {t.reference for t in adapter.catalog()}
    assert adapter.measure("Gearbox", "mass").magnitude > 0


async def test_veraltete_form_wird_nicht_gemessen():
    doc = gearbox()
    doc.objects["Body"]["state"] = ["Touched"]
    adapter = await BridgeAdapter.load(FakeCad(doc), ["Gearbox"])
    with pytest.raises(Unsupported, match="recompute"):
        adapter.measure("Gearbox#Body", "volume")


def test_mengen_auf_dem_draht():
    assert decode_quantity({"kind": "quantity", "value": 2.7e-06, "unit": "kg/mm^3"}) == 2.7e-06 * ureg.kg / ureg.mm**3
    assert decode_quantity(6) == 6 * ureg.dimensionless
    assert freecad_text(100 * ureg.mm) == "100.0 mm"
    assert freecad_text(1.5 * ureg.kg) == "1.5 kg"
    assert freecad_text(2.7 * ureg.g / ureg.cm**3) == "2.7e-06 kg/mm^3"


# -- Gates and verification ---------------------------------------------------

async def test_gates_pruefen_die_zuordnung():
    s = await gearbox_session()
    checks = {(c.sysml_part, c.attribute): c for c in
              check_mapping(s["mapping"], s["catalog"], s["by_key"], s["pool"])}
    assert checks[("housing", "length")].verdict == "valid"
    # The cover's part entry names an object that does not exist.
    assert checks[("cover", "thickness")].verdict == "invalid"


def _uniqueness(attributes):
    from app.projects.bds.gates import gate_uniqueness

    mapping = parse_mapping("version: 2\nparts:\n  - {sysml_part: shaft, adapter: freecad, "
                            "cad_object: Doc#Shaft, status: confirmed}\nattributes:\n" + attributes)
    return [gate_uniqueness(e, mapping).verdict for e in mapping.attributes]


def test_a_tolerance_band_is_not_a_conflict():
    """A lower and an upper bound on the same attribute, measured the same way."""
    entry = ("  - {sysml_part: shaft, attribute: radius, requirement: %s, method: cylinder_radius,"
             " args: {kind: boss, axis: X}, status: confirmed}\n")
    assert _uniqueness(entry % "MinRadius" + entry % "MaxRadius") == ["valid", "valid"]


def test_two_measurements_for_one_attribute_are_a_conflict():
    assert _uniqueness(
        "  - {sysml_part: shaft, attribute: radius, requirement: MinRadius, method: cylinder_radius,"
        " args: {kind: boss, axis: X}, status: confirmed}\n"
        "  - {sysml_part: shaft, attribute: radius, requirement: MaxRadius, method: cylinder_radius,"
        " args: {kind: boss, axis: Z}, status: confirmed}\n") == ["invalid", "invalid"]


def test_two_entries_for_one_requirement_stay_a_conflict():
    entry = ("  - {sysml_part: shaft, attribute: radius, requirement: MinRadius, method: cylinder_radius,"
             " args: {kind: boss}, status: confirmed}\n")
    assert _uniqueness(entry + entry) == ["invalid", "invalid"]


async def test_verify_urteile_und_luecken():
    s = await gearbox_session()
    run = verify.run(s["requirements"], s["skipped"], s["mapping"], s["pool"]).to_dict()
    statuses = {v["requirement"]: v["status"] for v in run["verdicts"]}
    assert statuses == {"MaxHousingLength": "compliant", "MinBoreRadius": "compliant",
                        "MaxAssemblyMass": "compliant"}
    # A part entry that is only proposed is no mapping at all -- a gap, never a pass.
    assert any("MaxCoverThickness" in gap and "not confirmed" in gap for gap in run["gaps"])
    assert run["summary"]["not_checked"] == 1
    assert run["context"]["cad_adapter"] == "freecad" and run["context"]["mapping_digest"]


async def test_eintrag_ohne_requirement_wird_benannt():
    mapping = GEARBOX_MAPPING.replace("    requirement: MinBoreRadius\n", "")
    s = await gearbox_session(mapping_text=mapping)
    run = verify.run(s["requirements"], s["skipped"], s["mapping"], s["pool"])
    assert any(g.startswith("MinBoreRadius:") and "without a requirement (boreRadius)" in g for g in run.gaps)


async def test_verify_meldet_verletzung():
    doc = gearbox()
    doc.objects["Body"]["geometry"]["tightBoundBox"]["lengths"][0] = 99.0
    s = await gearbox_session(FakeCad(doc))
    run = verify.run(s["requirements"], s["skipped"], s["mapping"], s["pool"])
    assert [v.requirement.requirement_id for v in run.violations] == ["MaxHousingLength"]
    assert format(run.violations[0].deviation, "~P") == "4.0 mm"


# -- Proposals ----------------------------------------------------------------

async def test_difflib_schlaegt_vor_und_gates_filtern():
    s = await gearbox_session(mapping_text="version: 2\nparts:\nattributes:\n")
    ranked, dropped = await propose_run(DifflibProposer(), s["catalog"], s["mapping"], s["by_key"], s["pool"])
    best = {(p.sysml_part, p.attribute): p for p in ranked}
    assert best[("housing", "boreRadius")].method == "cylinder_radius"
    assert best[("housing", "boreRadius")].args == {"kind": "hole"}
    assert best[("cover", "thickness")].cad_object == "Gearbox#Body001"
    assert best[("cover", "thickness")].args == {"axis": "Z"}
    # Every candidate past the gates names something that exists.
    assert all(s["catalog"].target(p.cad_object) for p in ranked)


async def test_ki_antwort_wird_gegen_den_katalog_geprueft():
    s = await gearbox_session(mapping_text="version: 2\nparts:\nattributes:\n")
    recorded = json.dumps({"candidates": [
        {"sysml_part": "housing", "attribute": "length", "cad_object": "Gearbox#Body", "method": "bbox_size",
         "axis": "X", "kind": None, "parameter_name": None, "confidence": 0.9, "rationale": "name"},
        {"sysml_part": "housing", "attribute": "length", "cad_object": "Gearbox#Nope", "method": "bbox_size",
         "axis": "X", "kind": None, "parameter_name": None, "confidence": 0.9, "rationale": "invented"},
        {"sysml_part": "cover", "attribute": "length", "cad_object": "Gearbox#Body001", "method": "bbox_size",
         "axis": None, "kind": None, "parameter_name": None, "confidence": 0.8, "rationale": "no axis"},
        {"sysml_part": "cover", "attribute": "mass", "cad_object": "Gearbox#Body001", "method": "mass",
         "axis": None, "kind": None, "parameter_name": None, "confidence": 2, "rationale": "too sure"},
    ]})

    class Recorded(LlmProposer):
        async def _ask(self, excerpt):
            assert "cad_object Gearbox#Body" in excerpt and "(inside gearbox)" in excerpt
            return self._replay()

    proposer = Recorded(model="test", recorded=recorded)
    kept = await proposer.propose(s["catalog"])
    assert [(p.sysml_part, p.attribute, p.cad_object) for p in kept] == [("housing", "length", "Gearbox#Body")]
    assert kept[0].provenance["model"] == "test" and kept[0].provenance["prompt_digest"]
    assert len(proposer.dropped) == 3


def test_ki_antwort_im_codeblock_mit_text_wird_gelesen():
    # deepseek-v4.1-flash on Ollama Cloud ignores `format`: fenced JSON, then prose.
    fenced = '```json\n{\n  "candidates": []\n}\n```\n\nNo candidate: no `axes` line.'
    assert parse_answer(fenced) == {"candidates": []}
    assert parse_answer(' {"candidates": [1]} ') == {"candidates": [1]}
    assert parse_answer("```json\n[]\n```\n\n**Why nothing is mapped** ...") == {"candidates": []}
    with pytest.raises(json.JSONDecodeError):
        parse_answer("No candidate: nothing matches.")
    with pytest.raises(json.JSONDecodeError):
        parse_answer('```json\n{"candidates": [{"sysml_part": "housing"')   # truncated: nothing salvaged


async def test_auszug_ist_deterministisch_und_vollstaendig():
    s = await gearbox_session()
    excerpt = render_catalog(s["catalog"])
    assert excerpt == render_catalog(s["catalog"])
    assert "contains: Gearbox#Body, Gearbox#Body001 -- this is their assembly" in excerpt
    assert "axes for bbox_size: length X" in excerpt
    assert json_schema()["$defs"]["AiCandidate"]["additionalProperties"] is False


def test_proposal_store_merkt_sich_ablehnungen(tmp_path):
    path = tmp_path / "proposals.yaml"
    candidate = Proposal(id="", sysml_part="housing", attribute="length", adapter="freecad",
                         cad_object="Gearbox#Body", method="bbox_size", args={"axis": "X"})
    stored, added = add([], [candidate])
    save_proposals(stored, path)
    again, added_again = add(load_proposals(path), [candidate])
    assert [p.id for p in added] == ["p-01"] and added_again == []


# -- Confirmation -------------------------------------------------------------

async def test_bestaetigen_schreibt_textuell_und_verknuepft_requirement(workspace_dir):
    workspace = save_workspace("gearbox", "Gearbox", "Gearbox")
    workspace.mapping_path.write_text(
        "# my comment stays\nversion: 2\n\nparts:\n\nattributes:\n", encoding="utf-8")
    s = await gearbox_session(mapping_text=workspace.mapping_path.read_text(encoding="utf-8"))
    candidate = Proposal(id="", sysml_part="housing", attribute="length", adapter="freecad",
                         cad_object="Gearbox#Body", method="bbox_size", args={"axis": "X"},
                         proposed_by="baseline:difflib", confidence=0.8)
    stored, _ = add([], [candidate])
    save_proposals(stored, workspace.proposals_path)

    with pytest.raises(BdsError, match="no requirement"):
        confirm_mod.confirm(workspace, "p-01", s["catalog"], s["by_key"], s["pool"], requirement="Nope")

    result = confirm_mod.confirm(workspace, "p-01", s["catalog"], s["by_key"], s["pool"],
                                 requirement="MaxHousingLength")
    assert result["part_usable"] is True
    text = workspace.mapping_path.read_text(encoding="utf-8")
    assert text.startswith("# my comment stays\n")
    mapping = load_mapping(workspace.mapping_path)
    assert mapping.attributes[0].requirement == "MaxHousingLength"
    assert mapping.attributes[0].author == "baseline:difflib"
    assert load_proposals(workspace.proposals_path)[0].status == "confirmed"

    with pytest.raises(BdsError) as exc:
        confirm_mod.reject(workspace, "p-01", "too late")
    assert exc.value.code == "bds_proposal_decided"

    # The confirmed entry is now used by a run.
    run = verify.run(s["requirements"], [], mapping, s["pool"])
    assert [v.requirement.requirement_id for v in run.verdicts] == ["MaxHousingLength"]


async def test_ungueltiger_vorschlag_wird_nicht_bestaetigt(workspace_dir):
    workspace = save_workspace("gearbox", "Gearbox", "Gearbox")
    s = await gearbox_session(mapping_text=GEARBOX_MAPPING)
    workspace.mapping_path.write_text(GEARBOX_MAPPING, encoding="utf-8")
    # housing is mapped to Gearbox#Body; a proposal naming the cover body conflicts.
    wrong = Proposal(id="", sysml_part="housing", attribute="width", adapter="freecad",
                     cad_object="Gearbox#Body001", method="bbox_size", args={"axis": "Y"})
    assert check_proposal(wrong, s["mapping"], s["catalog"], s["by_key"], s["pool"]).verdict == "invalid"
    stored, _ = add([], [wrong])
    save_proposals(stored, workspace.proposals_path)
    with pytest.raises(BdsError) as exc:
        confirm_mod.confirm(workspace, "p-01", s["catalog"], s["by_key"], s["pool"])
    assert exc.value.code == "bds_gate_failed"
    assert workspace.mapping_path.read_text(encoding="utf-8") == GEARBOX_MAPPING


# -- Limits into FreeCAD ------------------------------------------------------

async def test_grenzwerte_trockenlauf_und_schreiben(workspace_dir):
    workspace = save_workspace("gearbox", "Gearbox", "Gearbox")
    cad = FakeCad(gearbox())
    s = await gearbox_session(cad)
    state = {"sysml_commit_id": "c1"}

    dry = await limits.sync(workspace, s["requirements"], s["mapping"], s["pool"], state)
    assert dry["changes"] == 3 and cad.operations_log == []
    assert not workspace.sync_log_path.exists()

    applied = await limits.sync(workspace, s["requirements"], s["mapping"], s["pool"], state, apply=True)
    assert applied["changes"] == 3 and len(cad.operations_log) == 1
    sheet = cad.documents["Gearbox"].objects["SysML"]
    assert sheet["cells"]["A1"]["content"] == MARKER
    aliases = {c["alias"]: c["content"] for c in sheet["cells"].values() if c.get("alias")}
    assert aliases == {"MaxAssemblyMass": "=1.5 kg", "MaxHousingLength": "=95.0 mm", "MinBoreRadius": "=8.0 mm"}
    assert json.loads(workspace.sync_log_path.read_text(encoding="utf-8"))["sysml_commit_id"] == "c1"

    # A second sync of an unchanged model has nothing to say.
    s = await gearbox_session(cad)
    again = await limits.sync(workspace, s["requirements"], s["mapping"], s["pool"], state, apply=True)
    assert again["changes"] == 0 and len(cad.operations_log) == 1


async def test_fremdes_sheet_wird_nicht_beschrieben(workspace_dir):
    workspace = save_workspace("gearbox", "Gearbox", "Gearbox", limits_sheet="Params")
    cad = FakeCad(gearbox())
    s = await gearbox_session(cad)
    result = await limits.sync(workspace, s["requirements"], s["mapping"], s["pool"], {}, apply=True)
    assert result["failures"] == 1 and "not the sync's" in result["documents"][0]["error"]
    assert cad.operations_log == []


# -- Scoring, workspaces ------------------------------------------------------

async def test_score_gegen_gold():
    s = await gearbox_session(mapping_text="version: 2\nparts:\nattributes:\n")
    gold = [
        GoldEntry("housing", "boreRadius", ({"adapter": "freecad", "cad_object": "Gearbox#Body",
                                             "method": "cylinder_radius", "args": {"kind": "hole"}},)),
        GoldEntry("cover", "boreRadius"),           # expects silence? the cover has a bore too
    ]
    result = await score(DifflibProposer(), gold, s["catalog"], s["by_key"], s["pool"])
    assert result.hit_at_1 >= 1 and result.gold_entries == 2


def test_workspaces(workspace_dir):
    assert list_workspaces() == []
    save_workspace("box", "CubeFreecad", "Cube", axes={"length": "y", "width": "z", "height": "x"})
    workspace = load_workspace("box")
    assert workspace.axes["length"] == "Y" and workspace.limits_sheet == "SysML"
    assert load_mapping(workspace.mapping_path).attributes == []
    with pytest.raises(BdsError):
        save_workspace("box", "CubeFreecad", axes={"length": "X", "width": "X"})
    with pytest.raises(BdsError) as exc:
        load_workspace("nope")
    assert exc.value.status == 404


async def test_material_mit_dichte_macht_masse_messbar():
    adapter = await BridgeAdapter.load(FakeCad(cube(material=ALUMINIUM)), ["Cube"])
    assert "mass" in adapter.catalog()[0].methods
    assert math.isclose(adapter.measure("Cube", "mass").to("kg").magnitude, 100 * 200 * 300 * 2.7e-6)


# -- Over HTTP: the routes, against FakeFlexo, FakeCad and FakeOllama ------------

BASE = "/api/projects/bds/workspaces"


@pytest_asyncio.fixture
async def platform(handshake, workspace_dir):
    """Backend with Flexo holding the gearbox model, FreeCAD holding its document."""
    flexo, ollama = FakeFlexo(), FakeOllama()
    flexo.url = await flexo.start()
    await ollama.start()
    sysml = SysmlService(SysmlConfig(api_url=flexo.url, timeout_s=5))
    project = await sysml.client.create_project("Gearbox")
    changes = [{"identity": {"@id": e["@id"]}, "payload": e} for e in elements("gearbox")]
    await sysml.client.post_commit(project["@id"], changes, description="gearbox")
    ai = AiService(AiConfig(api_key=ollama.key, base_url=ollama.url, default_model="gpt-oss:120b",
                            status_ttl_s=0))
    async with running_backend(sysml_service=sysml, ai_service=ai) as backend:
        cad = FakeCad(gearbox())
        backend.state.registry.modules["bds"].ctx.cad = cad
        backend.cad, backend.ollama = cad, ollama

        async def put(path, body):
            async with backend.http.put(backend.url + path, json=body) as response:
                return response.status, await response.json()

        backend.put = put
        yield backend
    await sysml.stop()
    await ollama.stop()
    await flexo.stop()


async def test_ablauf_ueber_http(platform):
    status, body = await platform.put(BASE + "/gearbox", {"sysml_project": "Gearbox", "cad_document": "Gearbox"})
    assert status == 200 and body["sysml_project"] == "Gearbox"

    status, catalog = await platform.get(BASE + "/gearbox/catalog")
    assert status == 200
    assert len(catalog["requirements"]) == 4 and catalog["sysml_commit_id"]
    assert {t["reference"] for t in catalog["cad"]} == {"Gearbox", "Gearbox#Body", "Gearbox#Body001"}

    status, proposed = await platform.post(BASE + "/gearbox/proposals", json={"proposer": "difflib"})
    assert status == 200 and proposed["stored"]
    housing_length = next(p for p in proposed["candidates"]
                          if (p["sysml_part"], p["attribute"]) == ("housing", "length"))
    status, listed = await platform.get(BASE + "/gearbox/proposals?status=proposed&check=true")
    assert all(p["check"]["verdict"] in ("valid", "unknown") for p in listed["proposals"])
    proposal_id = next(p["id"] for p in listed["proposals"] if p["cad_object"] == housing_length["cad_object"]
                       and (p["sysml_part"], p["attribute"], p["method"]) == ("housing", "length",
                                                                               housing_length["method"]))

    status, confirmed = await platform.post(BASE + "/gearbox/proposals/%s/confirm" % proposal_id,
                                            json={"requirement": "MaxHousingLength"})
    assert status == 200, confirmed
    status, mapping = await platform.get(BASE + "/gearbox/mapping")
    assert [a["requirement"] for a in mapping["attributes"]] == ["MaxHousingLength"]

    status, run = await platform.post(BASE + "/gearbox/verify", json={})
    assert status == 200
    assert [(v["requirement"], v["status"]) for v in run["verdicts"]] == [("MaxHousingLength", "compliant")]
    assert run["summary"]["not_checked"] == 3 and run["violated"] is False
    status, last = await platform.get(BASE + "/gearbox/verify/last")
    assert status == 200 and last == run
    status, listed = await platform.get(BASE)
    [workspace] = listed["workspaces"]
    assert workspace["counts"] == {"parts_confirmed": 1, "attributes_confirmed": 1,
                                   "proposals_pending": len(proposed["stored"]) - 1}
    assert workspace["last_run"]["summary"]["compliant"] == 1

    status, gates = await platform.get(BASE + "/gearbox/gates")
    assert status == 200 and gates["summary"]["invalid"] == 0

    status, sync = await platform.post(BASE + "/gearbox/sync", json={"apply": True})
    assert status == 200 and sync["changes"] == 1
    assert platform.cad.operations_log[0]["name"] == "BDS: SysML limits"


async def test_ki_vorschlag_ueber_http(platform):
    await platform.put(BASE + "/gearbox", {"sysml_project": "Gearbox", "cad_document": "Gearbox"})
    platform.ollama.replies.append(answer(json.dumps({"candidates": [
        {"sysml_part": "cover", "attribute": "thickness", "cad_object": "Gearbox#Body001", "method": "bbox_size",
         "axis": "Z", "kind": None, "parameter_name": None, "confidence": 0.9, "rationale": "Cover body, Z"},
    ]})))
    status, proposed = await platform.post(BASE + "/gearbox/proposals", json={"proposer": "ai"})
    assert status == 200, proposed
    assert proposed["proposer"] == "ai:gpt-oss:120b"
    assert [(p["sysml_part"], p["attribute"]) for p in proposed["candidates"]] == [("cover", "thickness")]
    chat = platform.ollama.chats[-1]
    assert chat["format"]["type"] == "object"          # the response schema reached Ollama
    assert "cad_object Gearbox#Body001" in chat["messages"][-1]["content"]


async def test_fehler_im_plattform_format(platform):
    status, body = await platform.get(BASE + "/nope")
    assert status == 404 and body["error"]["code"] == "bds_workspace_not_found"
    status, body = await platform.put(BASE + "/x", {"sysml_project": "Unknown"})
    assert status == 404 and body["error"]["code"] == "sysml_project_not_found"
    await platform.put(BASE + "/gearbox", {"sysml_project": "Gearbox", "cad_document": "Gearbox"})
    status, body = await platform.post(BASE + "/gearbox/proposals", json={"proposer": "magic"})
    assert status == 400 and body["error"]["code"] == "bds_unknown_proposer"
    status, body = await platform.get(BASE + "/gearbox/verify/last")
    assert status == 404 and body["error"]["code"] == "bds_no_run"
    status, body = await platform.get(BASE + "/gearbox/score")
    assert status == 404 and body["error"]["code"] == "bds_no_gold"
