"""Agent code in its own process: result, errors, what it does not inherit, the timeout."""

import json
import time

import pytest

from app.ai import code_runner
from app.ai.code_runner import MARKER, RunnerConfig, parse, run_python
from app.ai.tools import python_tools


def test_antwort_des_harness_wird_gelesen():
    answer = {"result": {"x": 1}, "error": None, "stdout": "hi\n", "stderr": ""}
    out = parse(0, "noise" + MARKER + json.dumps(answer) + "\n", "", time.monotonic())
    assert out["ok"] and out["result"] == {"x": 1} and out["stdout"] == "hi\n"


async def test_tool_mischt_inputs_und_data(monkeypatch):
    seen = {}

    async def fake(code, inputs=None, cfg=None):
        seen.update(code=code, inputs=inputs)
        return {"ok": True, "result": 1}

    monkeypatch.setattr(code_runner, "run_python", fake)

    async def provided():
        return {"a": 1, "b": 2}

    tool = python_tools(inputs=provided)[0]
    out = json.loads(await tool.ainvoke({"code": "result = 1", "data": {"b": 3}}))
    assert out == {"ok": True, "result": 1}
    assert seen == {"code": "result = 1", "inputs": {"a": 1, "b": 3}}


async def test_result_und_main():
    out = await run_python("print('hi')\nresult = sum(inputs['x'])", {"x": [1, 2, 3]})
    assert out["ok"] and out["result"] == 6 and out["stdout"] == "hi\n"
    out = await run_python("def main(inputs):\n    return {'n': len(inputs['x'])}", {"x": [1, 2]})
    assert out["result"] == {"n": 2}


async def test_exception_wird_zurueckgegeben():
    out = await run_python("1 / 0")
    assert not out["ok"] and out["error"]["type"] == "ZeroDivisionError" and "<agent>" in out["error"]["traceback"]


async def test_secrets_nicht_in_der_umgebung(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "secret")
    monkeypatch.setenv("BRIDGE_TOKEN", "secret")
    out = await run_python("import os\nresult = sorted(k for k in os.environ if 'OLLAMA' in k or 'BRIDGE' in k)")
    assert out["result"] == []


async def test_endlosschleife_wird_beendet():
    started = time.monotonic()
    out = await run_python("while True: pass", cfg=RunnerConfig(timeout_s=1))
    assert out["error"]["type"] == "Timeout"
    assert time.monotonic() - started < 8


async def test_ausgabe_wird_gekappt():
    out = await run_python("print('x' * 100000)")
    assert out["ok"] and out["stdout"].endswith("...(truncated)")
    assert len(out["stdout"]) <= code_runner.MAX_OUTPUT + len(" ...(truncated)")


async def test_arbeitsverzeichnis_ist_temporaer():
    out = await run_python("import os\nresult = os.getcwd()")
    assert "agent-py-" in out["result"]
    check = await run_python("import os\nresult = os.path.exists(inputs['cwd'])", {"cwd": out["result"]})
    assert check["result"] is False


async def test_backend_bibliotheken_sind_da_aber_nicht_app():
    out = await run_python("import pint\nresult = pint.UnitRegistry()('700 mm').to('m').magnitude")
    assert out["ok"] and out["result"] == pytest.approx(0.7)
    assert (await run_python("import app"))["error"]["type"] == "ModuleNotFoundError"


async def test_umlaute_kommen_unveraendert_an():
    out = await run_python("result = inputs['s'] + 'ü'\nprint(result)", {"s": "Größe €"})
    assert out["result"] == "Größe €ü" and out["stdout"] == "Größe €ü\n"


async def test_harter_absturz():
    out = await run_python("print('vorher')\nimport os\nos._exit(3)")
    assert out["error"]["type"] == "Crashed" and "exit code 3" in out["error"]["message"]
