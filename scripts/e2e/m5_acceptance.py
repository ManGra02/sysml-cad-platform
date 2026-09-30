"""M5 acceptance: real bridge, real backend, simulated browser.

    cd backend
    uv run python ../scripts/e2e/m5_acceptance.py

The flow from the plan -- only then is M5 considered achieved:
    stop the bridge -> create three objects in FreeCAD -> start the bridge
    -> the browser is up to date WITHOUT reloading.

Plus the paths that show all three parts working together:
a change in FreeCAD reaches the browser; a PATCH from the browser reaches
FreeCAD and comes back as our own echo.

Prerequisite: ports 8000 and 8765 free (quit FreeCAD with a running bridge
first) and FreeCAD 1.1 at the usual path or in FREECAD_PYTHON.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

import aiohttp
import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "backend"))

from app.main import create_app  # noqa: E402

FREECAD_PYTHON = os.environ.get("FREECAD_PYTHON", r"D:\Program Files\FreeCAD 1.1\bin\python.exe")
BACKEND = "http://127.0.0.1:8000"
ORIGIN = {"Origin": "http://127.0.0.1:8000"}
DOC = "E2EDoc"

results = []



def replace_with_retry(src, dst, attempts=50):
    """os.replace with retries.

    Windows refuses the replace while the other process has the target file
    open for reading -- a harness detail, not one of the platform.
    """
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(src, dst)

def check(name, condition, info=""):
    results.append((name, bool(condition)))
    print("  %s  %s%s" % ("OK  " if condition else "FAIL", name, (" | %s" % (info,)) if info else ""))


class FreeCADProcess:
    """Controls freecad_driver.py via command files."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="e2e_m5_")
        self.next_id = 0
        env = dict(os.environ, PYTHONNOUSERSITE="1")
        self.process = subprocess.Popen(
            [FREECAD_PYTHON, os.path.join(HERE, "freecad_driver.py"), self.dir], env=env
        )

    async def run(self, command, timeout=30):
        self.next_id += 1
        tmp = os.path.join(self.dir, "cmd.json.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"id": self.next_id, "cmd": command}, handle)
        replace_with_retry(tmp, os.path.join(self.dir, "cmd.json"))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with open(os.path.join(self.dir, "ack.json"), encoding="utf-8") as handle:
                    ack = json.load(handle)
                if ack["id"] == self.next_id:
                    if not ack["ok"]:
                        raise RuntimeError("%s -> %s" % (command, ack["result"]))
                    return ack["result"]
            except (OSError, ValueError, KeyError):
                pass
            await asyncio.sleep(0.05)
        raise TimeoutError("FreeCAD does not respond to %r" % command)

    def kill(self):
        if self.process.poll() is None:
            self.process.kill()


async def wait_for(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return False


async def main():
    freecad = FreeCADProcess()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=8000,
                                           log_level="warning", lifespan="on"))
    server_task = asyncio.create_task(server.serve())
    await wait_for(lambda: server.started)

    frames = []
    session = aiohttp.ClientSession(headers=ORIGIN)
    try:
        print("\n[1] Start FreeCAD, start the bridge, create a document")
        await freecad.run("start")
        await freecad.run("newdoc")

        ws = await session.ws_connect(BACKEND + "/ws")

        async def collect():
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    frames.append(json.loads(message.data))

        collector = asyncio.create_task(collect())

        def events(type_):
            return [e for f in frames if f.get("type") == "events" for e in f["events"]
                    if e["type"] == type_]

        def bridge_state():
            states = [f["bridge"]["state"] for f in frames if f.get("type") == "hello"]
            states += [f["status"]["state"] for f in frames if f.get("type") == "bridge.status"]
            return states[-1] if states else None

        ok = await wait_for(lambda: bridge_state() == "ok")
        check("Browser sees the bridge as connected", ok, bridge_state())

        async def tree_count():
            async with session.get(BACKEND + "/api/cad/documents/%s/tree" % DOC) as response:
                body = await response.json()
                return response.status, len(body.get("nodes", {}))

        status, before = await tree_count()
        check("Tree readable via the backend", status == 200, "%d objects" % before)

        print("\n[2] A change in FreeCAD reaches the browser")
        await freecad.run("set Box Length 55")
        got = await wait_for(lambda: [e for e in events("cad.changed")
                                      if e.get("obj") == "Box" and e["origin"] == "freecad:user"])
        check("cad.changed with origin freecad:user", got)

        print("\n[3] A PATCH from the browser reaches FreeCAD")
        async with session.patch(BACKEND + "/api/cad/documents/%s/objects/Box" % DOC,
                                 json={"Length": "66 mm"},
                                 headers={"X-Request-Id": "e2e-1"}) as response:
            patch_body = await response.json()
        check("PATCH successful", response.status == 200 and patch_body.get("atomic"), patch_body.get("applied"))
        value = await freecad.run("get Box Length")
        check("Value set in FreeCAD", value == 66.0, value)
        echo = await wait_for(lambda: [e for e in events("cad.changed") if e["origin"] == "bridge:e2e-1"])
        check("own echo recognizable (bridge:e2e-1)", echo)
        echo_rev = [e["rev"] for e in events("cad.changed")
                    if e["origin"] == "bridge:e2e-1" and e["obj"] == "Box"]
        check("Response and event carry the same revision",
              echo_rev and echo_rev[-1] == patch_body.get("rev"), (echo_rev, patch_body.get("rev")))

        print("\n[4] ACCEPTANCE: stop the bridge -> create 3 objects -> start the bridge")
        await freecad.run("stop")
        down = await wait_for(lambda: bridge_state() in ("unreachable", "unconfigured"))
        check("Browser learns: bridge gone", down, bridge_state())

        async with session.get(BACKEND + "/api/status") as response:
            check("Backend keeps running", response.status == 200)

        count = await freecad.run("add 3")
        check("three objects created in FreeCAD (without bridge)", count == before + 3, count)

        resyncs_before = len(events("cad.resync"))
        await freecad.run("start")
        back = await wait_for(lambda: bridge_state() == "ok", timeout=15)
        check("Backend reconnects on its own", back)
        resynced = await wait_for(lambda: len(events("cad.resync")) > resyncs_before)
        reason = events("cad.resync")[-1]["reason"] if events("cad.resync") else None
        check("Browser receives cad.resync", resynced, reason)

        status, after = await tree_count()
        check("Browser sees all three new objects -- without reloading",
              after == before + 3, "%d -> %d" % (before, after))

        collector.cancel()
        await ws.close()
    finally:
        await session.close()
        try:
            await freecad.run("quit", timeout=10)
        except Exception:
            freecad.kill()
        server.should_exit = True
        await server_task

    failed = [name for name, ok in results if not ok]
    print("\n===== %d OK, %d FAIL =====" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
