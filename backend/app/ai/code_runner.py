"""Python code written by an agent, run in a separate Python process per call.

    out = await run_python("result = sum(inputs['x'])", {"x": [1, 2, 3]})
    out["result"]   # -> 6

The process uses the backend's interpreter, so the backend's libraries (pint ...)
are there, but not the ``app`` package. Data goes in as JSON on stdin (``inputs``),
the result comes back as JSON. The code either sets ``result`` or defines
``main(inputs)``; what it prints is returned as ``stdout``. Errors are returned,
never raised: ``error.type`` is the exception's name, or Timeout, Crashed.

This is NOT a sandbox. The environment is reduced (no API key, no bridge token) and
the working directory is temporary, but the code runs with the backend user's rights:
it can read and write files (backend/.env, bridge.json, data/) and use the network
(Flexo, the bridge). There is no memory or CPU limit, and the timeout only ends the
process itself, not processes it started. Run only what may do all of that.

Settings come from environment variables, falling back to backend/.env:

  CODE_EXEC_TIMEOUT_S   per call (default 10)
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass

from app import config

#: Characters of stdout/stderr kept per call
MAX_OUTPUT = 20_000
#: Separates the harness's answer from anything else on stdout
MARKER = "\x00agent-result\x00"
#: The only environment variables the process gets (Python on Windows needs SYSTEMROOT)
ENV_KEEP = ("SYSTEMROOT", "TEMP", "TMP", "PATH")
#: How long a killed process gets to go away
KILL_WAIT_S = 5

HARNESS = r"""
import io, json, sys, traceback

class Capped(io.TextIOBase):
    def __init__(self, limit):
        self.parts, self.size, self.limit, self.truncated = [], 0, limit, False
    def write(self, s):
        room = self.limit - self.size
        if len(s) > room:
            s, self.truncated = s[:max(room, 0)], True
        self.parts.append(s)
        self.size += len(s)
        return len(s)
    def text(self):
        return "".join(self.parts) + (" ...(truncated)" if self.truncated else "")

real = sys.stdout
job = json.loads(sys.stdin.read())
out, err = Capped(LIMIT), Capped(LIMIT)
sys.stdout, sys.stderr = out, err
answer = {"result": None, "error": None}
try:
    scope = {"inputs": job["inputs"], "__name__": "__agent__"}
    exec(compile(job["code"], "<agent>", "exec"), scope)
    answer["result"] = scope["main"](job["inputs"]) if callable(scope.get("main")) else scope.get("result")
except BaseException as exc:
    answer["error"] = {"type": type(exc).__name__, "message": str(exc),
                       "traceback": traceback.format_exc()[-4000:]}
finally:
    sys.stdout, sys.stderr = real, sys.__stderr__
answer["stdout"], answer["stderr"] = out.text(), err.text()
real.write(MARKER + json.dumps(answer, default=repr) + "\n")
real.flush()
""".replace("LIMIT", str(MAX_OUTPUT)).replace("MARKER", repr(MARKER))


@dataclass
class RunnerConfig:
    timeout_s: float = 10.0

    @classmethod
    def from_env(cls, env_file=None):
        values = {**config.read_env_file(env_file or config.ENV_FILE), **os.environ}
        return cls(timeout_s=float(values.get("CODE_EXEC_TIMEOUT_S") or cls.timeout_s))


def _cut(text):
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + " ...(truncated)"


def _failed(kind, message, started, stdout="", stderr=""):
    return {"ok": False, "result": None, "stdout": _cut(stdout), "stderr": _cut(stderr),
            "error": {"type": kind, "message": message},
            "duration_ms": round((time.monotonic() - started) * 1000)}


def parse(returncode, stdout, stderr, started):
    """The process's exit code and output -> the result of run_python."""
    at = stdout.rfind(MARKER)
    if at < 0:
        return _failed("Crashed", "no result from the process (exit code %s)" % returncode,
                       started, stdout, stderr)
    answer = json.loads(stdout[at + len(MARKER):])
    error = answer.get("error")
    return {"ok": error is None, "result": answer.get("result"), "stdout": answer.get("stdout", ""),
            "stderr": answer.get("stderr", ""), "error": error,
            "duration_ms": round((time.monotonic() - started) * 1000)}


async def run_python(code, inputs=None, cfg=None):
    """Run ``code`` in a new process -> {ok, result, stdout, stderr, error, duration_ms}."""
    cfg = cfg or RunnerConfig.from_env()
    started = time.monotonic()
    payload = json.dumps({"code": code, "inputs": inputs if inputs is not None else {}}, default=str).encode()
    env = {key: os.environ[key] for key in ENV_KEEP if key in os.environ}
    with tempfile.TemporaryDirectory(prefix="agent-py-", ignore_cleanup_errors=True) as cwd:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-X", "utf8", "-c", HARNESS, cwd=cwd, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(payload), cfg.timeout_s)
        except asyncio.TimeoutError:
            await _kill(proc)
            return _failed("Timeout", "no result after %g s" % cfg.timeout_s, started)
    return parse(proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace"), started)


async def _kill(proc):
    """End the process. Bounded: a process it started may keep the pipes open."""
    if proc.returncode is None:
        proc.kill()
    try:
        await asyncio.wait_for(proc.wait(), KILL_WAIT_S)
    except asyncio.TimeoutError:
        pass
