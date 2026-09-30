"""Remote-controlled FreeCAD for end-to-end tests (runs in FreeCAD's Python).

Headless, there is no Qt event loop. This script takes over its role:
it pumps the dispatch queue and the observer flush on the main thread -- just
as the Qt signal, heartbeat and 100 ms timer do in GUI mode.

It is controlled via command files in a directory:
    <dir>/cmd.json   {"id": n, "cmd": "..."}  -> execution
    <dir>/ack.json   {"id": n, "ok": true, "result": ...}

Commands: start, stop, newdoc, add <n>, set <obj> <prop> <value>, count, quit
"""

import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "bridge"))

import FreeCAD  # noqa: E402

from freecad_bridge import dispatch, observer, runner  # noqa: E402

DOC = "E2EDoc"



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

def execute(command):
    parts = command.split()
    name = parts[0]
    if name == "start":
        runner.start_bridge()
        return "started"
    if name == "stop":
        runner.stop_bridge()
        return "stopped"
    if name == "newdoc":
        doc = FreeCAD.newDocument(DOC)
        doc.UndoMode = 1
        doc.addObject("Part::Box", "Box")
        doc.recompute()
        return len(doc.Objects)
    if name == "add":
        doc = FreeCAD.getDocument(DOC)
        for index in range(int(parts[1])):
            doc.addObject("Part::Sphere", "Kugel%d" % index)
        doc.recompute()
        return len(doc.Objects)
    if name == "set":
        obj = FreeCAD.getDocument(DOC).getObject(parts[1])
        setattr(obj, parts[2], float(parts[3]))
        FreeCAD.getDocument(DOC).recompute()
        return getattr(obj, parts[2]).Value
    if name == "get":
        obj = FreeCAD.getDocument(DOC).getObject(parts[1])
        return getattr(obj, parts[2]).Value
    if name == "count":
        return len(FreeCAD.getDocument(DOC).Objects)
    raise ValueError("unknown command %r" % command)


def main(control_dir):
    cmd_path = os.path.join(control_dir, "cmd.json")
    ack_path = os.path.join(control_dir, "ack.json")
    last_id = None
    deadline = time.monotonic() + 300

    while time.monotonic() < deadline:
        # The role of the Qt event loop: drain the queue, flush the observer.
        dispatch.drain(reschedule=False)
        observer.flush_now("timer")

        try:
            with open(cmd_path, "r", encoding="utf-8") as handle:
                message = json.load(handle)
        except (OSError, ValueError):
            message = None

        if message and message.get("id") != last_id:
            last_id = message["id"]
            if message["cmd"] == "quit":
                runner.stop_bridge(quiet=True)
                _ack(ack_path, last_id, True, "quit")
                return 0
            try:
                result = execute(message["cmd"])
                _ack(ack_path, last_id, True, result)
            except Exception as exc:
                _ack(ack_path, last_id, False, "%s: %s" % (type(exc).__name__, exc))

        time.sleep(0.01)

    runner.stop_bridge(quiet=True)
    return 1


def _ack(path, message_id, ok, result):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"id": message_id, "ok": ok, "result": result}, handle)
    replace_with_retry(tmp, path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
