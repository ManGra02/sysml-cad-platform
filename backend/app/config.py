"""Backend configuration.

The backend NEVER imports FreeCAD. It therefore has to know on its own where
the bridge's handshake file lives -- it is FreeCAD's versioned user
directory (v1-1, with a hyphen), which is in a different place on each
operating system.

Overrides via environment variables:
  BRIDGE_HANDSHAKE   path to bridge.json (non-standard FreeCAD installation)
  BRIDGE_URL         talk to the bridge directly (tests, mock) ...
  BRIDGE_TOKEN       ... together with the token in that case
  PLATFORM_DEV       "1" additionally allows the Vite dev server as an origin
  PLATFORM_STATE_DIR where the backend writes its small bit of state
                     (active project); default ~/.sysml-cad-platform

Secrets such as OLLAMA_API_KEY may also live in backend/.env (gitignored,
see backend/.env.example); a real environment variable always wins.
"""

import os
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000

LOOPBACK_HOSTS = frozenset(["127.0.0.1", "localhost", "::1"])

FREECAD_VERSION_DIR = "v1-1"
HANDSHAKE_RELATIVE = Path("sysml-cad-platform") / "bridge.json"

#: Timeouts per route class. aiohttp's default is total=300 s -- with that,
#: a hanging recompute would freeze the UI for five minutes.
CONNECT_TIMEOUT_S = 1.0
READ_TIMEOUT_S = 5.0
WRITE_TIMEOUT_S = 35.0     # the bridge itself gives up after 30 s
RECOMPUTE_TIMEOUT_S = 65.0


def freecad_user_dir():
    """FreeCAD's user directory, without importing FreeCAD."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "FreeCAD" / FREECAD_VERSION_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "FreeCAD" / FREECAD_VERSION_DIR
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "FreeCAD" / FREECAD_VERSION_DIR


def handshake_path():
    override = os.environ.get("BRIDGE_HANDSHAKE")
    if override:
        return Path(override)
    return freecad_user_dir() / HANDSHAKE_RELATIVE


def bridge_override():
    """(url, token) if explicitly configured, otherwise None."""
    url = os.environ.get("BRIDGE_URL")
    token = os.environ.get("BRIDGE_TOKEN")
    if url and token:
        return url.rstrip("/"), token
    return None


def dev_mode():
    return os.environ.get("PLATFORM_DEV") == "1"


def allowed_origins():
    origins = {"http://127.0.0.1:%d" % PORT, "http://localhost:%d" % PORT}
    if dev_mode():
        origins |= {"http://127.0.0.1:5173", "http://localhost:5173"}
    return origins


def allowed_hosts():
    return ["127.0.0.1", "localhost", "[::1]"]


def state_dir():
    """Small, persistent backend state -- survives --reload and restarts."""
    override = os.environ.get("PLATFORM_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".sysml-cad-platform"


STATIC_DIR = Path(__file__).resolve().parent / "static"

#: backend/.env -- local secrets and settings, never committed
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def read_env_file(path):
    """KEY=VALUE lines (optional quotes) -> dict. Missing file -> {}."""
    values = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values
