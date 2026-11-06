"""CRA agent: understanding, guardrails, PLM verification, CAD search and the review loop.

No key, no database, no network: a scripted LLM stands in for Ollama (it "reads" part names
from a table and returns prepared profiles), the PLM is a fixed list of records.
"""

import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.ai import AiConfig, AiService
from app.projects.cra import agent as cra_agent, guardrails, plm
from app.projects.cra.agent import CraResult, Review, agent_tools, build_graph
from app.projects.cra.plm import PlmError
from app.projects.cra.profile import PartProfile
from app.projects.cra.session import CraSession
from app.projects.cra.specs import EXTRACT_PROMPT, GROUP_PROMPT
from app.projects.cra.tools import cra_tools
from conftest import running_backend


def rec(number, name, cad=(), material="", attributes=None, mass_kg=None):
    files = None if cad is None else [{"file": "%s.step" % number, "format": "step", "path": "x", "bbox": list(b)}
                                      for b in cad]
    return {"id": number, "item_number": number, "name": name, "attributes": attributes or {},
            "description": "", "material": material, "mass_kg": mass_kg, "part_type": "", "cad": files}


RECORDS = [
    rec("P0", "Timing pulley 18T bore 12", cad=[(40, 40, 20)]),
    rec("P1", "Timing pulley 42T bore 18", cad=()),
    rec("P2", "Timing pulley 18T bore 10", cad=[(40, 40, 20)]),
    rec("P3", "Belt sheave 18T bore 12", cad=[(40, 40, 20)]),
    rec("P4", "Bicycle tire 700c", cad=[(700, 700, 30)]),
    rec("B0", "Bolt, M10x60 Hex Head, DIN 933", cad=()),
    rec("B1", "Hex bolt M10x60 DIN 933, zinc", cad=[(66.7, 18.7, 16.2)]),       # head adds length: fine
    rec("B2", "Hex bolt M10x60 DIN 933", cad=[(30, 18, 16)]),                  # geometry 30 mm: wrong record
    rec("B3", "Hex bolt M8x60 DIN 933", cad=[(65, 15, 13)]),
]

SPECS = {
    "Timing pulley 18T bore 12": dict(category="pulley", material="steel", attrs={"teeth": 18, "bore_diameter_mm": 12}),
    "Timing pulley 42T bore 18": dict(category="pulley", material="steel", attrs={"teeth": 42, "bore_diameter_mm": 18}),
    "Timing pulley 18T bore 10": dict(category="pulley", material="steel", attrs={"teeth": 18, "bore_diameter_mm": 10}),
    "Belt sheave 18T bore 12": dict(category="sheave", material="steel", attrs={"teeth": 18, "bore_diameter_mm": 12}),
    "Bicycle tire 700c": dict(category="tire", material="rubber", attrs={"diameter_mm": 622}),
    "Bolt, M10x60 Hex Head, DIN 933": dict(category="bolt", attrs={"thread_size": "M10", "length_mm": 60}),
    "Hex bolt M10x60 DIN 933, zinc": dict(category="bolt", material="steel", attrs={"thread_size": "M10", "length_mm": 60}),
    "Hex bolt M10x60 DIN 933": dict(category="bolt", material="steel", attrs={"thread_size": "M10", "length_mm": 60}),
    "Hex bolt M8x60 DIN 933": dict(category="bolt", material="steel", attrs={"thread_size": "M8", "length_mm": 60}),
}

PROFILES = {
    "pulley": PartProfile(
        what_it_is="timing belt pulley", category="pulley", function="drives a belt", material="steel",
        properties={"teeth": 18, "bore_diameter_mm": 12, "outer_diameter_mm": 40, "length_mm": 20},
        rules=[dict(attribute="teeth", check="exact", value=18, critical=True, reason="must mesh with the belt"),
               dict(attribute="bore_diameter_mm", check="within", value=12, tolerance_pct=10, critical=True,
                    reason="sits on the 12 mm motor shaft"),
               dict(attribute="material", check="similar", value="steel", reason="preferred")]),
    "bolt": PartProfile(
        what_it_is="hex head bolt", category="bolt", function="fastens parts", material="steel",
        properties={"thread_size": "M10", "length_mm": 60, "diameter_mm": 10},
        rules=[dict(attribute="thread_size", check="exact", value="M10", critical=True, reason="mates the M10 nut"),
               dict(attribute="length_mm", check="within", value=60, tolerance_pct=5, reason="clamp length")]),
}
GROUPS = [["pulley", "sheave"]]


class Structured:
    def __init__(self, llm, schema):
        self.llm, self.schema = llm, schema

    async def ainvoke(self, prompt):
        self.llm.calls += 1
        if self.schema is PartProfile:
            text = str(prompt).lower()
            return next(p for key, p in PROFILES.items() if key in text.split("part:")[-1])
        return self.llm.structured.pop(0)


class FakeLlm:
    """Name reading and grouping from the tables above; profiles by keyword; scripted otherwise."""

    def __init__(self, replies=(), structured=()):
        self.calls = 0
        self.replies, self.structured = list(replies), list(structured)

    async def ainvoke(self, prompt):
        if not isinstance(prompt, str):                      # the agent itself (bound to tools)
            self.calls += 1
            return self.replies.pop(0)
        self.calls += 1
        if prompt.startswith(EXTRACT_PROMPT):
            items = json.loads(prompt[len(EXTRACT_PROMPT):])
            return json.dumps([{"id": i["id"], **SPECS[i["text"]]} for i in items])
        words = json.loads(prompt[len(GROUP_PROMPT):])
        return json.dumps([[w for w in g if w in words] for g in GROUPS])

    def with_structured_output(self, schema):
        return Structured(self, schema)

    def bind_tools(self, tools):
        return self


def session_for(tmp_path, llm=None, records=RECORDS):
    llm = llm or FakeLlm()

    async def load_parts():
        return records
    ctx = SimpleNamespace(ai=SimpleNamespace(chat_model=lambda **kw: llm))
    return CraSession(ctx, load_parts=load_parts, cache_file=tmp_path / "cache.json")


# -- guardrails (plain Python) -----------------------------------------------------


def rule(**kw):
    return guardrails.make_rule({"reason": "r", **kw})


def cand(number, category, **attrs):
    return {"item_number": number, "name": number, "category": category, "attrs": attrs, "plm_issues": []}


def test_guardrail_kappt_zu_lockere_regeln_des_agenten():
    fit = rule(attribute="boreDiameterMm", check="within", value=12, tolerance_pct=10, critical=True)
    assert fit["attribute"] == "bore_diameter_mm" and fit["tolerance_pct"] == 2 and fit["capped"]
    assert rule(attribute="length_mm", check="within", value=60, tolerance_pct=80)["tolerance_pct"] == 30
    assert rule(attribute="x", check="guess", value=1) is None


def test_guardrail_laesst_kritische_regeln_nicht_lockern():
    fit = rule(attribute="bore_diameter_mm", check="within", value=12, tolerance_pct=1, critical=True)
    assert guardrails.relax(fit, 10)[0] is None and "critical" in guardrails.relax(fit, 10)[1]
    soft = rule(attribute="length_mm", check="within", value=60, tolerance_pct=5)
    assert guardrails.relax(soft, 40)[0] is None                      # beyond 30 %
    assert guardrails.relax(soft, 15)[0]["tolerance_pct"] == 15


def test_status_fits_unverified_fails_suspicious():
    profile = {"category": "pulley"}
    rules = [rule(attribute="teeth", check="exact", value=18, critical=True),
             rule(attribute="bore_diameter_mm", check="within", value=12, tolerance_pct=1, critical=True)]
    groups = {"pulley": 0, "sheave": 0, "tire": 1}
    assert guardrails.evaluate(profile, rules, cand("A", "pulley", teeth=18, bore_diameter_mm=12), groups)["status"] == "fits"
    assert guardrails.evaluate(profile, rules, cand("B", "pulley", teeth=18), groups)["status"] == "unverified"
    bad = guardrails.evaluate(profile, rules, cand("C", "pulley", teeth=18, bore_diameter_mm=15), groups)
    assert bad["status"] == "fails" and bad["needs_tolerance_pct"] is None           # a fit is never relaxed
    sus = {**cand("D", "pulley", teeth=18, bore_diameter_mm=12), "plm_issues": ["geometry too small"]}
    assert guardrails.evaluate(profile, rules, sus, groups)["status"] == "suspicious"
    assert guardrails.evaluate(profile, rules, cand("E", "tire", teeth=18, bore_diameter_mm=12), groups) is None
    same_job = guardrails.evaluate(profile, rules, cand("F", "sheave", teeth=18, bore_diameter_mm=12), groups)
    assert same_job["status"] == "fits" and same_job["function"] == "same job, different kind"


def test_plm_widersprueche_ohne_fehlalarm():
    spec = {"material": "steel", "attrs": {"thread_size": "M10", "length_mm": 60}}
    assert guardrails.plausibility({}, spec, [66.7, 18.7, 16.2]) == []           # nominal length + head: fine
    assert "only 30 mm" in guardrails.plausibility({}, spec, [30, 18, 16])[0]
    record = {"material": "ABS", "attributes": {"lengthMm": "900"}}
    issues = guardrails.plausibility(record, {"material": "steel", "attrs": {"length_mm": 815}}, None)
    assert any("material" in i for i in issues) and any("lengthMm" in i for i in issues)


# -- session: understand, search, verify, relax, envelope ------------------------------


async def test_wiederverwendung_versteht_teil_und_findet_es(tmp_path):
    s = session_for(tmp_path)
    prof = await s.understand("motorPulley", "pulley for the motor, 18 teeth, 12 mm bore")
    assert prof["category"] == "pulley" and prof["guardrail_notes"] == ["bore_diameter_mm: tolerance capped to 2 % by the guardrails"]
    res = await s.search("motorPulley")
    numbers = [c["item_number"] for c in res["candidates"]]
    assert numbers[:2] == ["P0", "P3"] and res["candidates"][0]["status"] == "fits"
    assert "P4" not in numbers                                       # a tire is never a candidate
    assert next(c for c in res["candidates"] if c["item_number"] == "P2")["status"] == "fails"


async def test_cad_suche_fuer_plm_teil_ohne_cad(tmp_path):
    s = session_for(tmp_path)
    missing = await s.without_cad()
    assert {p["item_number"] for p in missing["parts"]} == {"P1", "B0"}
    await s.understand("B0", "bolt, M10x60 Hex Head, DIN 933")
    res = await s.search("B0", cad_required=True)
    status = {c["item_number"]: c["status"] for c in res["candidates"]}
    assert status == {"B1": "fits", "B2": "suspicious", "B3": "fails"}      # B0 itself and parts without CAD: out
    assert res["candidates"][0]["cad"] == ["step"]


async def test_plm_daten_werden_gegen_geometrie_geprueft(tmp_path):
    s = session_for(tmp_path)
    assert (await s.verify("B1"))["verdict"] == "consistent"
    bad = await s.verify("B2")
    assert bad["verdict"] == "suspicious" and "only 30 mm" in bad["contradictions"][0]
    assert (await s.overview())["with_contradictions"] == 1


async def test_lockern_nur_mit_guardrails(tmp_path):
    s = session_for(tmp_path)
    await s.understand("B0", "bolt M10x60")
    assert s.relax("B0", "thread_size", 10, "any thread")["relaxed"] is False
    ok = s.relax("B0", "length_mm", 12, "clamp length can vary by a washer")
    assert ok["relaxed"] and s.journal == ["B0: length_mm within 5 % -> 12 % (clamp length can vary by a washer)"]


async def test_huellmodell_aus_dem_verstaendnis(tmp_path):
    s = session_for(tmp_path)
    await s.understand("B0", "bolt M10x60")
    env = s.envelope("B0")
    assert env["type"] == "Part::Cylinder" and env["props"] == {"Radius": "5 mm", "Height": "60 mm"}


async def test_namen_werden_nur_einmal_gelesen(tmp_path):
    llm = FakeLlm()
    await session_for(tmp_path, llm).overview()
    first = llm.calls
    assert first == 1                                               # 9 names in one batch
    await session_for(tmp_path, llm).overview()                     # new session, cache from the file
    assert llm.calls == first


async def test_tools_liefern_json_und_fehler(tmp_path):
    tools = {t.name: t for t in cra_tools(session_for(tmp_path))}
    out = json.loads(await tools["search_parts"].ainvoke({"subject": "x"}))
    assert out["error"]["code"] == "not_understood"
    out = json.loads(await tools["plm_item"].ainvoke({"item_number": "nope"}))
    assert out["error"]["code"] == "item_not_found"


# -- the agent graph ---------------------------------------------------------------------


def test_agent_nutzt_keine_nachbarn():
    ctx = SimpleNamespace(sysml=None, cad=None, publish=lambda *a: None)
    names = {t.name for t in agent_tools(ctx, session=None)}
    assert "sysml_neighbours" not in names
    assert {"understand_part", "search_parts", "verify_part", "relax_rule", "sysml_attributes", "cad_tree"} <= names


async def test_reviewer_schickt_antwort_zurueck(tmp_path):
    result = CraResult(mission="find_cad", subject="B0", outcome="cad_found", item_number="B1", confidence="high")
    llm = FakeLlm(replies=[AIMessage("B1 fits"), AIMessage("B1 fits, verified")],
                  structured=[Review(approved=False, issues=["B1 was not verified"]), Review(approved=True), result])
    graph = build_graph(llm, cra_tools(session_for(tmp_path, llm)))
    state = await graph.ainvoke({"messages": [("user", "find CAD for B0")]})
    assert state["reviews"] == 2 and state["review_notes"][0]["issues"] == ["B1 was not verified"]
    assert "Reviewer" in state["messages"][2].content
    assert state["structured_response"].item_number == "B1"


async def test_reviewer_gibt_irgendwann_auf(tmp_path):
    no = Review(approved=False, issues=["still wrong"])
    llm = FakeLlm(replies=[AIMessage("a")] * 3, structured=[no, no, no, CraResult()])
    state = await build_graph(llm, []).ainvoke({"messages": [("user", "q")]})
    assert state["reviews"] == cra_agent.MAX_REVIEWS + 1 and state["structured_response"] == CraResult()


# -- PLM access and routes -------------------------------------------------------------


def test_plm_groesse_aus_cad_oder_attribut():
    assert plm.extents({"cad": [{"bbox": [16.2, 66.7, 18.7]}]}) == [66.7, 18.7, 16.2]
    assert plm.extents({"cad": [], "attributes": {"bboxMm": "[0.0, -170.0, -0.0, 3.0, 170.0, 250.0]"}}) == [340.0, 250.0, 3.0]
    assert plm.extents({"cad": None, "attributes": {}}) is None


def test_plm_einstellungen_aus_env_datei(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PGHOST=db.example\nPGDATABASE=cascadia2\n", encoding="utf-8")
    for name in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGPORT", "5433")
    s = plm.settings(env)
    assert (s["host"], s["port"], s["dbname"], s["user"]) == ("db.example", "5433", "cascadia2", "postgres")


async def test_routen_melden_fehlende_datenbank(handshake, monkeypatch):
    async def down(env_file=None):
        raise PlmError("plm_unavailable", "Cannot reach the PLM database")
    monkeypatch.setattr(plm, "load_parts", down)
    async with running_backend(ai_service=AiService(AiConfig(api_key="k", default_model="m"))) as backend:
        code, body = await backend.get("/api/projects/cra/plm/missing-cad")
        bad, _ = await backend.post("/api/projects/cra/envelope", json={"type": "Part::Feature", "props": {}})
    assert code == 503 and body["error"]["code"] == "plm_unavailable"
    assert bad == 422                                                # only boxes and cylinders


def test_plm_fasst_revisionen_zusammen():
    a = rec("PUC-9008", "Bolt, M10x60", cad=())
    b = {**rec("PUC-9008", "Bolt, M10x60", cad=[(66.7, 18.7, 16.2)]), "material": "steel"}
    (one,) = plm.merge([a, b])
    assert one["material"] == "steel" and len(one["cad"]) == 1          # the CAD of the other revision counts


def test_plm_teil_ohne_dateien_hat_kein_cad():
    row = ("id1", "PUC-1", "Bracket", {}, "", "", None, None, "")
    assert plm._record(row, {})["cad"] == []            # vault known, no files: no CAD
    assert plm._record(row, None)["cad"] is None        # no vault at all: unknown
