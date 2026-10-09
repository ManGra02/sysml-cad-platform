"""AI adapter: config, status, ctx.ai per project, the example agents -- against a fake Ollama.

No key and no network: fake_ollama.FakeOllama answers /api/tags and a scripted /api/chat.
"""

import pytest
import pytest_asyncio

from app.ai import AiConfig, AiError, AiService
from app.ai.service import model_available
from conftest import free_port, running_backend, wait_for
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
    ollama.replies = [tool_call("cad_documents"), answer("Ein Dokument: Doc")]
    async with running_backend(ai_service=AiService(config_for(ollama))) as backend:
        await wait_for(lambda: backend.state.bridge.state == "ok")
        code, body = await backend.post("/api/projects/cra/agent", json={"message": "Welche Dokumente?"})
    assert code == 200, body
    assert body["model"] == "gpt-oss:20b" and body["answer"] == "Ein Dokument: Doc"
    assert body["steps"][0]["tool"] == "cad_documents" and '"Doc"' in body["steps"][0]["result"]
    assert [c["model"] for c in ollama.chats] == ["gpt-oss:20b"] * 2
    assert ollama.chats[0]["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in ollama.chats[0]["tools"]} >= {"sysml_parts", "cad_tree"}


async def test_agent_ohne_key(handshake):
    async with running_backend(ai_service=AiService(AiConfig(default_model="m"))) as backend:
        code, body = await backend.post("/api/projects/bds/agent", json={"message": "hi"})
    assert code == 503 and body["error"]["code"] == "ai_not_configured"


async def test_agent_unbekanntes_modell(handshake, ollama):
    service = AiService(config_for(ollama, default_model="gone:1b"))
    async with running_backend(ai_service=service) as backend:
        code, body = await backend.post("/api/projects/bds/agent", json={"message": "hi"})
    assert code == 502 and body["error"]["code"] == "ai_model_not_found"
