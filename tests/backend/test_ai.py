"""AI adapter: config, status, ctx.ai per project, the example agents -- against a fake Ollama.

No key and no network: fake_ollama.FakeOllama answers /api/tags and a scripted /api/chat.
"""

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import BaseModel

from app.ai import AiConfig, AiError, AiService
from app.ai.agents import run
from app.ai.service import model_available
from app.ai.tools import calc_tools, progress_tool, sysml_tools
from app.sysml.config import SysmlConfig
from app.sysml.demo import load_sample
from app.sysml.service import SysmlService
from conftest import BrowserClient, free_port, running_backend, wait_for
from fake_flexo import FakeFlexo
from fake_ollama import FakeOllama, answer, tool_call


@pytest_asyncio.fixture
async def ollama():
    fake = FakeOllama()
    await fake.start()
    yield fake
    await fake.stop()


def config_for(fake, **kw):
    values = dict(api_key=fake.key, base_url=fake.url, default_model="gpt-oss:120b",
                  models={"cra": "gpt-oss:20b"}, status_ttl_s=0)
    values.update(kw)
    return AiConfig(**values)


# -- Config (offline) ----------------------------------------------------


def test_modell_pro_projekt_sonst_default():
    cfg = AiConfig(api_key="k", default_model="gpt-oss:120b", models={"cra": "gpt-oss:20b"})
    assert cfg.model_for("cra") == "gpt-oss:20b"
    assert cfg.model_for("bds") == "gpt-oss:120b"
    assert AiConfig().model_for("bds") is None


def test_env_schlaegt_env_datei(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('OLLAMA_API_KEY="from-file"\nOLLAMA_MODEL=m1\nOLLAMA_MODEL_BDS=m2\n', encoding="utf-8")
    for name in ("OLLAMA_API_KEY", "OLLAMA_MODEL", "OLLAMA_MODEL_BDS", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_MODEL_CRA", "m3")
    cfg = AiConfig.from_env(env_file)
    assert (cfg.api_key, cfg.base_url) == ("from-file", "https://ollama.com")
    assert (cfg.model_for("bds"), cfg.model_for("cra"), cfg.model_for("x")) == ("m2", "m3", "m1")
    monkeypatch.setenv("OLLAMA_API_KEY", "from-env")
    assert AiConfig.from_env(env_file).api_key == "from-env"


def test_latest_ist_dasselbe_modell():
    assert model_available("llama3", ["llama3:latest"])
    assert model_available("gpt-oss:120b", ["gpt-oss:120b"])
    assert not model_available("gpt-oss:20b", ["gpt-oss:120b"])


def test_ohne_key_kein_chat_model():
    ai = AiService(AiConfig(default_model="m")).for_project("bds")
    with pytest.raises(AiError) as exc:
        ai.chat_model()
    assert exc.value.code == "ai_not_configured"
    ai = AiService(AiConfig(api_key="k")).for_project("bds")
    with pytest.raises(AiError) as exc:
        ai.chat_model()
    assert exc.value.code == "ai_no_model"


# -- Status -------------------------------------------------------------


async def test_status_erreichbar_und_modelle(ollama):
    service = AiService(config_for(ollama, models={"cra": "nope:1b"}))
    service.for_project("bds"), service.for_project("cra")
    status = await service.status()
    await service.stop()
    assert status["reachable"] is True and status["configured"] is True
    assert status["projects"]["bds"] == {"model": "gpt-oss:120b", "available": True}
    assert status["projects"]["cra"] == {"model": "nope:1b", "available": False}


async def test_status_falscher_key(ollama):
    service = AiService(config_for(ollama, api_key="wrong"))
    status = await service.status()
    await service.stop()
    assert (status["reachable"], status["code"]) == (False, "ai_unauthorized")


async def test_status_nicht_erreichbar_ist_ein_normaler_zustand():
    service = AiService(AiConfig(api_key="k", base_url="http://127.0.0.1:%d" % free_port()))
    status = await service.status()
    await service.stop()
    assert (status["reachable"], status["code"]) == (False, "ai_unreachable")


async def test_status_ohne_key_fragt_nicht_nach(ollama):
    service = AiService(config_for(ollama, api_key=None))
    status = await service.status()
    await service.stop()
    assert (status["configured"], status["reachable"], status["code"]) == (False, False, "ai_not_configured")


async def test_status_wird_gecacht(ollama):
    service = AiService(config_for(ollama, status_ttl_s=60))
    assert (await service.status())["reachable"] is True
    ollama.key = "rotated"
    assert (await service.status())["reachable"] is True               # still the cached result
    assert (await service.status(refresh=True))["reachable"] is False
    await service.stop()


# -- In the real backend ------------------------------------------------


async def test_api_status_und_ctx_ai(handshake, ollama):
    service = AiService(config_for(ollama))
    async with running_backend(ai_service=service) as backend:
        code, status = await backend.get("/api/ai/status")
        assert code == 200 and status["reachable"] is True
        assert status["projects"]["bds"]["model"] == "gpt-oss:120b"
        assert status["projects"]["cra"]["model"] == "gpt-oss:20b"
        assert "test-key" not in str(status)                         # the key never leaves the backend
        modules = backend.state.registry.modules
        assert modules["bds"].ctx.ai.model == "gpt-oss:120b"
        assert modules["cra"].ctx.ai.model == "gpt-oss:20b"


async def test_agent_ruft_tools_mit_eigenem_modell(bridge, ollama):
    missing = {"parts": [{"sysml_id": "p1", "name": "motor", "reason": "no CAD object"}]}
    ollama.replies = [tool_call("cad_documents"), answer("Ein Dokument: Doc"), tool_call("MissingParts", **missing)]
    async with running_backend(ai_service=AiService(config_for(ollama))) as backend:
        await wait_for(lambda: backend.state.bridge.state == "ok")
        code, body = await backend.post("/api/projects/cra/agent", json={"message": "Welche Dokumente?"})
    assert code == 200, body
    assert body["model"] == "gpt-oss:20b" and body["answer"] == "Ein Dokument: Doc"
    assert body["steps"][0]["tool"] == "cad_documents" and '"Doc"' in body["steps"][0]["result"]
    assert body["result"] == missing                       # CRA's structured MissingParts
    assert [c["model"] for c in ollama.chats] == ["gpt-oss:20b"] * 3
    assert ollama.chats[0]["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in ollama.chats[0]["tools"]} >= {
        "sysml_parts", "sysml_find", "sysml_diff", "cad_tree", "calculate", "report_progress"}
    # The structured step offers the schema as a tool (Ollama Cloud ignores "format")
    assert [t["function"]["name"] for t in ollama.chats[2]["tools"]] == ["MissingParts"]


async def test_agent_ohne_key(handshake):
    async with running_backend(ai_service=AiService(AiConfig(default_model="m"))) as backend:
        code, body = await backend.post("/api/projects/cra/agent", json={"message": "hi"})
    assert code == 503 and body["error"]["code"] == "ai_not_configured"


async def test_agent_unbekanntes_modell(handshake, ollama):
    service = AiService(config_for(ollama, models={"cra": "gone:1b"}))
    async with running_backend(ai_service=service) as backend:
        code, body = await backend.post("/api/projects/cra/agent", json={"message": "hi"})
    assert code == 502 and body["error"]["code"] == "ai_model_not_found"


# -- Writing tools ------------------------------------------------------


def test_sysml_tools_ohne_write_sind_nur_lesend():
    ctx = SimpleNamespace(sysml=None)
    assert "sysml_set_attribute_value" not in {t.name for t in sysml_tools(ctx)}
    assert "sysml_set_attribute_value" in {t.name for t in sysml_tools(ctx, write=True)}


@pytest_asyncio.fixture
async def ebike():
    """Flexo stand-in with the e-bike demo -> (SysmlService, motor mass attribute id)."""
    flexo = FakeFlexo()
    service = SysmlService(SysmlConfig(api_url=await flexo.start(), timeout_s=5))
    project = await service.client.create_project("EBike Demo")
    await service.client.post_commit(project["@id"], load_sample("ebike")["change"], description="seed")
    snap = await service.snapshot("EBike Demo")
    motor = snap.find("motor", kind="part")[0]
    mass = next(a for a in snap.attributes_of(motor.id) if a.name == "mass")
    yield service, mass.id
    await service.stop()
    await flexo.stop()


async def test_agent_schreibt_sysml_attribut(ollama, ebike):
    service, mass_id = ebike
    ollama.replies = [
        tool_call("sysml_set_attribute_value", project="EBike Demo", attribute_id=mass_id,
                  value=11200, unit="g", description="Agent: mass from CAD"),
        answer("Masse auf 11.2 kg gesetzt."),
    ]
    ctx = SimpleNamespace(sysml=service)
    agent = AiService(config_for(ollama)).for_project("bds").agent(sysml_tools(ctx, write=True))
    result = await run(agent, "Setze die Motormasse auf 11200 g")

    written = json.loads(result["steps"][0]["result"])
    snap = await service.snapshot("EBike Demo")
    assert snap.version == written["commit"] and written["description"] == "Agent: mass from CAD"
    assert (snap.attribute(mass_id).value, snap.attribute(mass_id).unit) == (11.2, "kg")


async def test_agent_sieht_schreibfehler_und_laeuft_weiter(ollama, ebike):
    service, _ = ebike
    ollama.replies = [tool_call("sysml_set_attribute_value", project="EBike Demo", attribute_id="nope", value=1),
                      answer("Attribut nicht gefunden.")]
    agent = AiService(config_for(ollama)).for_project("bds").agent(
        sysml_tools(SimpleNamespace(sysml=service), write=True))
    result = await run(agent, "Setze nope auf 1")
    assert "sysml_attribute_not_found" in result["steps"][0]["result"]
    assert result["answer"] == "Attribut nicht gefunden."


# -- More read tools, arithmetic, progress, structured result ---------------


async def call(tools, tool_name, **args):
    """Run one tool directly (as the ToolNode would) -> parsed JSON result."""
    return json.loads(await next(t for t in tools if t.name == tool_name).ainvoke(args))


@pytest.mark.parametrize("expression, result", [
    ("(2.4 + 3.1) * 4", 22.0), ("0.1 + 0.2", 0.3), ("sqrt(16) / 2", 2.0), ("max(3, 7, 5)", 7),
    ("sum([1, 2, 3])", 6), ("-2 ** 2", -4), ("17 // 5 + 17 % 5", 5), ("round(2.345, 2)", 2.35),
])
async def test_calculate(expression, result):
    assert (await call(calc_tools(), "calculate", expression=expression))["result"] == result


@pytest.mark.parametrize("expression", [
    "__import__('os')", "a + 1", "(1).real", "2 ** 10000", "(9 ** 100) ** 100", "open('x')", "1 +", "'a' * 3",
])
async def test_calculate_verweigert(expression):
    assert "error" in await call(calc_tools(), "calculate", expression=expression)


async def test_convert_units():
    tools = calc_tools()
    assert await call(tools, "convert_units", value=11200, from_unit="g", to_unit="kg") == {"value": 11.2, "unit": "kg"}
    assert "error" in await call(tools, "convert_units", value=1, from_unit="kg", to_unit="m")


async def test_report_progress_geht_an_den_browser():
    frames = []
    ctx = SimpleNamespace(publish=lambda kind, payload=None: frames.append((kind, payload)))
    assert await call([progress_tool(ctx)], "report_progress", message="Lese den CAD-Baum") == {"reported": True}
    assert frames == [("agent.progress", {"message": "Lese den CAD-Baum"})]


async def test_report_progress_im_backend(handshake):
    """Real ProjectContext: the frame is <module id>.agent.progress."""
    async with running_backend(ai_service=AiService(AiConfig())) as backend:
        browser = await BrowserClient(backend.url).connect()
        ctx = backend.state.registry.modules["cra"].ctx
        await call([progress_tool(ctx)], "report_progress", message="Suche Teile")
        await wait_for(lambda: any(f.get("type") == "cra.agent.progress" for f in browser.frames))
        await browser.close()
    frame = next(f for f in browser.frames if f.get("type") == "cra.agent.progress")
    assert frame["data"] == {"message": "Suche Teile"}


async def test_sysml_find(ebike):
    service, mass_id = ebike
    tools = sysml_tools(SimpleNamespace(sysml=service))
    found = await call(tools, "sysml_find", project="EBike Demo", name="Motor", kind="part")
    assert [h["name"] for h in found["hits"]] == ["motor"] and found["truncated"] is False
    assert (await call(tools, "sysml_find", project="EBike Demo", name="nothing"))["hits"] == []


async def test_sysml_history_und_diff(ebike):
    service, mass_id = ebike
    await service.write_attribute_value("EBike Demo", mass_id, 11200, unit="g", description="mass from CAD")
    tools = sysml_tools(SimpleNamespace(sysml=service))
    history = (await call(tools, "sysml_history", project="EBike Demo"))["commits"]
    assert [c["description"] for c in history] == ["mass from CAD", "seed"]          # newest first
    assert len((await call(tools, "sysml_history", project="EBike Demo", limit=1))["commits"]) == 1

    diff = await call(tools, "sysml_diff", project="EBike Demo",
                      base_commit=history[1]["id"], compare_commit=history[0]["id"])
    assert diff["summary"]["attributes_changed"] == 1
    [changed] = diff["attributes_changed"]
    assert (changed["owner"], changed["name"], changed["to"]) == ("motor", "mass", "11.2 [kg]")
    assert changed["from"] != changed["to"]
    assert diff["elements_added"] == [] and diff["elements_removed"] == []


class Verdict(BaseModel):
    ok: bool
    count: int


async def structured_run(ollama, *replies):
    ollama.replies = [answer("Alles gut."), *replies]
    agent = AiService(config_for(ollama)).for_project("bds").agent([], response_format=Verdict)
    return await run(agent, "Prüfe")


async def test_strukturiertes_ergebnis_per_tool_call(ollama):
    result = await structured_run(ollama, tool_call("Verdict", ok=True, count=3))
    assert result["answer"] == "Alles gut." and result["result"] == {"ok": True, "count": 3}
    assert "resultError" not in result and len(ollama.chats) == 2


async def test_strukturiertes_ergebnis_prosa_dann_json(ollama):
    """What deepseek/gpt-oss on Ollama Cloud do: ignore the tool, answer in prose -> second try."""
    result = await structured_run(ollama, answer("**Zusammenfassung**: 3 Teile, alles ok"),
                                  answer('Hier:\n```json\n{"ok": true, "count": 3}\n```'))
    assert result["result"] == {"ok": True, "count": 3} and len(ollama.chats) == 3
    assert '"count"' in ollama.chats[2]["messages"][-1]["content"]   # the schema is in the prompt


async def test_strukturiertes_ergebnis_scheitert_ohne_abbruch(ollama):
    result = await structured_run(ollama, answer("Prosa"), answer("immer noch Prosa"))
    assert result["answer"] == "Alles gut."                           # the run itself stays usable
    assert result["result"] is None and "Verdict" in result["resultError"]


async def test_ohne_response_format_kein_result(ollama):
    ollama.replies = [answer("Hallo")]
    result = await run(AiService(config_for(ollama)).for_project("bds").agent([]), "Hi")
    assert "result" not in result and len(ollama.chats) == 1

