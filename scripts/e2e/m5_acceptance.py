"""M5-Abnahme: echte Bruecke, echtes Backend, simulierter Browser.

    cd backend
    uv run python ../scripts/e2e/m5_acceptance.py

Der Ablauf aus dem Plan -- M5 gilt erst dann als erreicht:
    Bruecke stoppen -> in FreeCAD drei Objekte anlegen -> Bruecke starten
    -> der Browser ist aktuell, OHNE neu zu laden.

Dazu kommen die Wege, die das Zusammenspiel aller drei Teile zeigen:
Aenderung in FreeCAD erreicht den Browser; PATCH aus dem Browser erreicht
FreeCAD und kommt als eigenes Echo zurueck.

Voraussetzung: Ports 8000 und 8765 frei (FreeCAD mit laufender Bruecke vorher
beenden) und FreeCAD 1.1 unter dem ueblichen Pfad oder in FREECAD_PYTHON.
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
    """os.replace mit Wiederholung.

    Windows verweigert das Ersetzen, solange der andere Prozess die Zieldatei
    gerade zum Lesen offen hat -- ein Harness-Detail, keines der Plattform.
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
    """Steuert freecad_driver.py ueber Befehlsdateien."""

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
        raise TimeoutError("FreeCAD antwortet nicht auf %r" % command)

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
        print("\n[1] FreeCAD starten, Bruecke starten, Dokument anlegen")
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
        check("Browser sieht Bruecke als verbunden", ok, bridge_state())

        async def tree_count():
            async with session.get(BACKEND + "/api/cad/documents/%s/tree" % DOC) as response:
                body = await response.json()
                return response.status, len(body.get("nodes", {}))

        status, before = await tree_count()
        check("Baum ueber das Backend lesbar", status == 200, "%d Objekte" % before)

        print("\n[2] Aenderung in FreeCAD erreicht den Browser")
        await freecad.run("set Box Length 55")
        got = await wait_for(lambda: [e for e in events("cad.changed")
                                      if e.get("obj") == "Box" and e["origin"] == "freecad:user"])
        check("cad.changed mit Herkunft freecad:user", got)

        print("\n[3] PATCH aus dem Browser erreicht FreeCAD")
        async with session.patch(BACKEND + "/api/cad/documents/%s/objects/Box" % DOC,
                                 json={"Length": "66 mm"},
                                 headers={"X-Request-Id": "e2e-1"}) as response:
            patch_body = await response.json()
        check("PATCH erfolgreich", response.status == 200 and patch_body.get("atomic"), patch_body.get("applied"))
        value = await freecad.run("get Box Length")
        check("Wert in FreeCAD gesetzt", value == 66.0, value)
        echo = await wait_for(lambda: [e for e in events("cad.changed") if e["origin"] == "bridge:e2e-1"])
        check("eigenes Echo erkennbar (bridge:e2e-1)", echo)
        echo_rev = [e["rev"] for e in events("cad.changed")
                    if e["origin"] == "bridge:e2e-1" and e["obj"] == "Box"]
        check("Antwort und Ereignis tragen dieselbe Revision",
              echo_rev and echo_rev[-1] == patch_body.get("rev"), (echo_rev, patch_body.get("rev")))

        print("\n[4] ABNAHME: Bruecke stoppen -> 3 Objekte anlegen -> Bruecke starten")
        await freecad.run("stop")
        down = await wait_for(lambda: bridge_state() in ("unreachable", "unconfigured"))
        check("Browser erfaehrt: Bruecke weg", down, bridge_state())

        async with session.get(BACKEND + "/api/status") as response:
            check("Backend laeuft weiter", response.status == 200)

        count = await freecad.run("add 3")
        check("drei Objekte in FreeCAD angelegt (ohne Bruecke)", count == before + 3, count)

        resyncs_before = len(events("cad.resync"))
        await freecad.run("start")
        back = await wait_for(lambda: bridge_state() == "ok", timeout=15)
        check("Backend verbindet sich selbst neu", back)
        resynced = await wait_for(lambda: len(events("cad.resync")) > resyncs_before)
        reason = events("cad.resync")[-1]["reason"] if events("cad.resync") else None
        check("Browser bekommt cad.resync", resynced, reason)

        status, after = await tree_count()
        check("Browser sieht alle drei neuen Objekte -- ohne Neuladen",
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
