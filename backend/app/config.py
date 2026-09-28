"""Konfiguration des Backends.

Das Backend importiert FreeCAD NIE. Wo die Handshake-Datei der Bruecke liegt,
muss es deshalb selbst wissen -- es ist FreeCADs versioniertes
Benutzerverzeichnis (v1-1, mit Bindestrich), das je Betriebssystem woanders
liegt.

Overrides per Umgebungsvariable:
  BRIDGE_HANDSHAKE   Pfad zu bridge.json (abweichende FreeCAD-Installation)
  BRIDGE_URL         Bruecke direkt ansprechen (Tests, Mock) ...
  BRIDGE_TOKEN       ... dann zusammen mit dem Token
  PLATFORM_DEV       "1" erlaubt zusaetzlich den Vite-Dev-Server als Origin
  PLATFORM_STATE_DIR wohin das Backend seinen kleinen Zustand schreibt
                     (aktives Projekt); Standard ~/.sysml-cad-platform
"""

import os
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000

LOOPBACK_HOSTS = frozenset(["127.0.0.1", "localhost", "::1"])

FREECAD_VERSION_DIR = "v1-1"
HANDSHAKE_RELATIVE = Path("sysml-cad-platform") / "bridge.json"

#: Zeitgrenzen je Routenklasse. aiohttps Default ist total=300 s -- damit
#: haenge ein haengender Recompute die UI fuenf Minuten lang auf.
CONNECT_TIMEOUT_S = 1.0
READ_TIMEOUT_S = 5.0
WRITE_TIMEOUT_S = 35.0     # die Bruecke selbst bricht nach 30 s ab
RECOMPUTE_TIMEOUT_S = 65.0


def freecad_user_dir():
    """FreeCADs Benutzerverzeichnis, ohne FreeCAD zu importieren."""
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
    """(url, token) wenn fest konfiguriert, sonst None."""
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
    """Kleiner, dauerhafter Zustand des Backends -- ueberlebt --reload und Neustarts."""
    override = os.environ.get("PLATFORM_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".sysml-cad-platform"


STATIC_DIR = Path(__file__).resolve().parent / "static"
