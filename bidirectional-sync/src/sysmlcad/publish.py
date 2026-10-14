"""Publish a SysML notebook without clicking through JupyterLab.

    python -m sysmlcad.publish notebooks/04_publish_box2.ipynb
    make publish NB=notebooks/04_publish_box2.ipynb

Runs the notebook's code cells, in order, on the SysML kernel of the Jupyter
container (`make jupyter` on the host first), over Jupyter's REST and websocket
API. The last cell is the `%publish`, so the model lands on the API server the
kernel is configured for -- which must be this project's, not the public
community server. The kernel prints its target as `API base path: ...`, and
this module checks it against `SYSML_API_URL` and says so loudly when they
differ. A publish cannot be recalled; the check is there so it is at least
noticed at once.

Then capture it for offline runs: `make capture PROJECT=<name>`.

`websockets` is needed and is not in requirements.txt: CI never publishes.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import SYSML_API_URL

JUPYTER_URL = os.environ.get("SYSMLCAD_JUPYTER_URL", "http://jupyter:8888")
JUPYTER_TOKEN = os.environ.get("SYSMLCAD_JUPYTER_TOKEN", "sysmlcad")
KERNEL = "sysml"


def _request(code: str, session: str) -> dict:
    return {
        "header": {
            "msg_id": uuid.uuid4().hex, "username": "sysmlcad", "session": session,
            "msg_type": "execute_request", "version": "5.3",
            "date": datetime.now(timezone.utc).isoformat(),
        },
        "parent_header": {}, "metadata": {}, "buffers": [], "channel": "shell",
        "content": {"code": code, "silent": False, "store_history": True,
                    "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
    }


async def _execute(kernel_id: str, cells: list[str]) -> tuple[bool, str]:
    """Run the cells one by one; stop at the first error. Returns success and
    everything the kernel printed."""
    import websockets

    url = re.sub(r"^http", "ws", JUPYTER_URL) + f"/api/kernels/{kernel_id}/channels?token={JUPYTER_TOKEN}"
    session = uuid.uuid4().hex
    printed: list[str] = []

    def say(text: str) -> None:
        printed.append(text)
        print(text, end="" if text.endswith("\n") else "\n")

    # Jupyter completes the handshake only once the kernel is up, and a cold
    # SysML kernel (a JVM) took 16 s -- past websockets' default of 10 s.
    async with websockets.connect(url, max_size=None, open_timeout=120) as ws:
        for code in cells:
            request = _request(code, session)
            await ws.send(json.dumps(request))
            say(f">>> {code.strip().splitlines()[0][:70]}\n")
            reply, idle, reported_error = None, False, False
            while not (idle and reply):
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=600))
                if message.get("parent_header", {}).get("msg_id") != request["header"]["msg_id"]:
                    continue
                kind, content = message["msg_type"], message["content"]
                if kind == "stream":
                    say(content["text"])
                    # The SysML kernel reports a syntax error as printed text
                    # and still answers `status: ok`. Going on would run the
                    # `%publish` cell on a model that did not parse.
                    if any(line.startswith("ERROR") for line in content["text"].splitlines()):
                        reported_error = True
                elif kind in ("execute_result", "display_data"):
                    say(content["data"].get("text/plain", ""))
                elif kind == "error":
                    say(f"ERROR {content.get('ename')}: {content.get('evalue')}\n")
                elif kind == "status" and content["execution_state"] == "idle":
                    idle = True
                elif kind == "execute_reply":
                    reply = content["status"]
            if reply != "ok" or reported_error:
                say("stopped: this cell failed, the remaining cells were not run\n")
                return False, "".join(printed)
    return True, "".join(printed)


def publish(notebook: Path) -> int:
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("error: publishing needs `websockets` (pip install websockets)", file=sys.stderr)
        return 2

    data = json.loads(notebook.read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in data["cells"] if c["cell_type"] == "code"]
    if not cells:
        print(f"error: {notebook} has no code cells", file=sys.stderr)
        return 2

    headers = {"Authorization": f"token {JUPYTER_TOKEN}"}
    with httpx.Client(base_url=JUPYTER_URL, headers=headers, timeout=120) as client:
        try:
            started = client.post("/api/kernels", json={"name": KERNEL})
            started.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"error: no Jupyter at {JUPYTER_URL} ({exc}). Run `make jupyter` "
                  f"on the host first.", file=sys.stderr)
            return 2
        kernel_id = started.json()["id"]
        try:
            ok, output = asyncio.run(_execute(kernel_id, cells))
        finally:
            client.delete(f"/api/kernels/{kernel_id}")

    target = re.search(r"API base path:\s*(\S+)", output)
    if target and target.group(1).rstrip("/") != SYSML_API_URL.rstrip("/"):
        print(f"\nWARNING: the kernel published to {target.group(1)}, not to "
              f"{SYSML_API_URL}. Check kernel.json in the Jupyter image.", file=sys.stderr)
        return 1
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m sysmlcad.publish notebooks/<notebook>.ipynb")
        return 2
    return publish(Path(args[0]))


if __name__ == "__main__":
    raise SystemExit(main())
