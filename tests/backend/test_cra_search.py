"""CRA part search: function + dimensions instead of names -- with a fake LLM and fake PLM parts.

No key, no database, no network: the fake LLM "reads" the part names from a table, the PLM
returns a fixed list. What is tested is the matching in Python and the caching.
"""

import json
from types import SimpleNamespace

import pytest

from app.projects.cra import matching, plm
from app.projects.cra.finder import Finder
from app.projects.cra.plm import PlmError
from app.projects.cra.specs import EXTRACT_PROMPT, GROUP_PROMPT
from app.projects.cra.tools import cra_tools
from conftest import running_backend
from app.ai import AiConfig, AiService

REQ_TEXT = "pulley: drives a belt"
REQUIRED = {"partType": "Pulley", "function": "drives a belt", "teeth": 18,
            "boreDiameterMm": 12, "material": "Steel"}

SPECS = {
    REQ_TEXT: dict(category="pulley", type="pulley", function="drives a belt"),
    "Timing pulley 18T bore 12": dict(category="pulley", material="steel", attrs={"teeth": 18, "bore_diameter_mm": 12}),
    "Timing pulley 42T bore 18": dict(category="pulley", material="steel", attrs={"teeth": 42, "bore_diameter_mm": 18}),
    "Timing pulley 18T bore 10": dict(category="pulley", material="steel", attrs={"teeth": 18, "bore_diameter_mm": 10}),
    "Belt sheave 18T bore 12": dict(category="sheave", material="steel", attrs={"teeth": 18, "bore_diameter_mm": 12}),
    "Bicycle tire 700c": dict(category="tire", material="rubber", attrs={"diameter_mm": 622}),
}
PARTS = [{"item_number": "P%d" % i, "name": name, "attributes": {}}
         for i, name in enumerate(n for n in SPECS if n != REQ_TEXT)]
GROUPS = [["pulley", "sheave"]]


class FakeLlm:
    """Answers the two prompts of specs.py from the tables above and counts the calls."""

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, prompt):
        self.calls += 1
        if prompt.startswith(EXTRACT_PROMPT):
            items = json.loads(prompt[len(EXTRACT_PROMPT):])
            return json.dumps([{"id": i["id"], **SPECS[i["text"]]} for i in items])
        words = json.loads(prompt[len(GROUP_PROMPT):])
        return json.dumps([[w for w in g if w in words] for g in GROUPS])


def finder_for(tmp_path, llm, parts=PARTS):
    async def load_parts():
        return parts
    ctx = SimpleNamespace(ai=SimpleNamespace(chat_model=lambda **kw: llm))
    return Finder(ctx, load_parts=load_parts, cache_file=tmp_path / "cache.json")


# -- matching (pure Python) -------------------------------------------------


def spec(category, **attrs):
    return {"category": category, "type": "", "function": "", "material": "", "attrs": attrs}


def test_gleiche_art_und_masse_gewinnt_vor_aehnlichem():
    req = spec("pulley", teeth=18, bore_diameter_mm=12)
    cands = [dict(spec("pulley", teeth=42, bore_diameter_mm=18), item_number="A", name="a"),
             dict(spec("pulley", teeth=18, bore_diameter_mm=12), item_number="B", name="b"),
             dict(spec("sheave", teeth=18, bore_diameter_mm=12), item_number="C", name="c")]
    res = matching.rank(req, cands, 10, {"pulley": 0, "sheave": 0})
    assert res["best"]["item_number"] == "B" and res["best"]["score"] == 0.9   # material unknown: 0.5
    assert res["passed"] == 2                       # the sheave does the same job, but scores lower
    assert res["near_misses"][0]["item_number"] == "A"


def test_andere_art_wird_nie_vorgeschlagen():
    req = spec("tire", diameter_mm=622)
    res = matching.rank(req, [dict(spec("pulley", diameter_mm=622), item_number="A", name="a")], 30, {})
    assert res["best"] is None and res["same_function"] == 0


def test_passmasse_bleiben_auch_mit_mehr_toleranz_streng():
    req = spec("bearing", bore_diameter_mm=15, outer_diameter_mm=35)
    cand = dict(spec("bearing", bore_diameter_mm=12.7, outer_diameter_mm=36), item_number="A", name="a")
    res = matching.rank(req, [cand], 30, {})
    assert res["best"] is None
    assert res["near_misses"][0]["needs_tolerance_pct"] is None      # no tolerance can fix a bore


def test_groesse_mit_toleranz_und_mindestwerte():
    req = spec("bracket", length_mm=100, load_rating_kn=5)
    cand = dict(spec("bracket", length_mm=108, load_rating_kn=4), item_number="A", name="a")
    near = matching.rank(req, [cand], 10, {})["near_misses"][0]
    assert near["failures"] == ["load_rating_kn 4 vs 5"]            # 8 % length is fine, too little load is not
    ok = dict(spec("bracket", length_mm=108, load_rating_kn=6), item_number="B", name="b")
    assert matching.rank(req, [ok], 5, {})["near_misses"][0]["needs_tolerance_pct"] == 8
    assert matching.rank(req, [ok], 10, {})["best"]["item_number"] == "B"


def test_zu_wenig_pruefbare_werte():
    req = spec("screw", thread_size="M6", length_mm=20, diameter_mm=6)
    cand = dict(spec("screw", length_mm=20), item_number="A", name="a")
    assert matching.rank(req, [cand], 10, {})["best"] is None       # only 1 of 3 values can be checked


def test_requirement_aus_sysml_namen():
    assert matching.snake("boreDiameterMm") == "bore_diameter_mm"
    assert matching.requirement_text(REQUIRED) == REQ_TEXT
    req = matching.requirement_spec(REQUIRED, None)
    assert req["category"] == "pulley" and req["material"] == "steel"
    assert req["attrs"] == {"teeth": 18.0, "bore_diameter_mm": 12.0}


# -- search with fake LLM and fake PLM ---------------------------------------


async def test_suche_findet_teil_nach_funktion_und_massen(tmp_path):
    res = await finder_for(tmp_path, FakeLlm()).find(REQUIRED)
    assert res["best"] == {"item_number": "P0", "name": "Timing pulley 18T bore 12", "score": 1.0}
    assert (res["checked"], res["same_function"], res["passed"]) == (5, 4, 2)    # the tire is never a candidate
    failed = {m["item_number"]: m["failures"] for m in res["near_misses"]}
    assert "bore_diameter_mm 10 vs 12" in failed["P2"] and set(failed) == {"P1", "P2"}


async def test_zweite_suche_braucht_kein_llm(tmp_path):
    llm = FakeLlm()
    await finder_for(tmp_path, llm).find(REQUIRED)
    first = llm.calls                                  # names (1 batch) + groups
    assert first == 2
    await finder_for(tmp_path, llm).find(REQUIRED)     # new Finder: cache comes from the file
    assert llm.calls == first


async def test_toleranz_ueber_30_prozent_wird_gekappt(tmp_path):
    res = await finder_for(tmp_path, FakeLlm()).find(REQUIRED, tolerance_pct=80)
    assert res["tolerance_pct"] == matching.MAX_TOL_PCT


async def test_tool_liefert_json_und_fehler_als_ergebnis(tmp_path):
    tool = cra_tools(None, finder=finder_for(tmp_path, FakeLlm()))[0]
    assert tool.name == "find_matching_parts"
    out = json.loads(await tool.ainvoke({"attributes": REQUIRED}))
    assert out["best"]["item_number"] == "P0"

    async def broken():
        raise PlmError("plm_unavailable", "no database")
    finder = finder_for(tmp_path, FakeLlm())
    finder.load_parts = broken
    out = json.loads(await cra_tools(None, finder=finder)[0].ainvoke({"attributes": REQUIRED}))
    assert out == {"error": {"code": "plm_unavailable", "message": "no database"}}


# -- PLM access and route ---------------------------------------------------


def test_plm_einstellungen_aus_env_datei(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PGHOST=db.example\nPGDATABASE=cascadia2\n", encoding="utf-8")
    for name in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGPORT", "5433")
    s = plm.settings(env)
    assert (s["host"], s["port"], s["dbname"], s["user"]) == ("db.example", "5433", "cascadia2", "postgres")


async def test_route_meldet_fehlende_datenbank(handshake, monkeypatch):
    async def down(env_file=None):
        raise PlmError("plm_unavailable", "Cannot reach the PLM database")
    monkeypatch.setattr(plm, "load_parts", down)
    async with running_backend(ai_service=AiService(AiConfig(api_key="k", default_model="m"))) as backend:
        code, body = await backend.post("/api/projects/cra/search", json={"attributes": REQUIRED})
        too_much, _ = await backend.post("/api/projects/cra/search",
                                         json={"attributes": REQUIRED, "tolerance_pct": 80})
    assert code == 503 and body["error"]["code"] == "plm_unavailable"
    assert too_much == 422                              # the tolerance limit is checked by the route
