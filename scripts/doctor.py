"""Diagnose der Entwicklungsumgebung.

Laeuft in BEIDEN Pythons -- FreeCADs gebuendeltem und der Backend-venv -- und
prueft, was erfahrungsgemaess schiefgeht. Jede Meldung nennt die Behebung.

Der Grund fuer dieses Skript: "Bruecke nicht verbunden" ist ein Normalzustand
und verraet keine Ursache. Ohne doctor sucht jede Person im Team dieselbe
halbe Stunde.

Aufruf:
    "<FreeCAD>/bin/python.exe" scripts/doctor.py
    uv run python scripts/doctor.py
"""

import json
import os
import shutil
import socket
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(REPO, "bridge")

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
_results = []


def report(level, what, detail="", fix=""):
    _results.append((level, what, detail, fix))
    line = "[%s] %s" % (level, what)
    if detail:
        line += " | " + str(detail)
    print(line)
    if fix and level != OK:
        print("       -> " + fix)


# -- Python und Umgebung ------------------------------------------------


def check_python():
    version = "%d.%d.%d" % sys.version_info[:3]
    in_freecad = _freecad_module() is not None
    report(OK, "Python", "%s (%s)" % (version, "FreeCAD" if in_freecad else "extern"))

    if in_freecad and sys.version_info[:2] != (3, 11):
        report(
            WARN,
            "Python-Version in FreeCAD",
            version,
            "cad_contract muss zu 3.11 passen; kein PEP-695 verwenden.",
        )


def check_user_site():
    """Das user-site schattet FreeCADs gebuendelte Pakete."""
    import site

    try:
        user_site = site.getusersitepackages()
    except Exception:
        return
    enabled = site.ENABLE_USER_SITE
    exists = bool(user_site) and os.path.isdir(user_site)

    if enabled and exists and _freecad_module() is not None:
        report(
            WARN,
            "user-site aktiv",
            user_site,
            "PYTHONNOUSERSITE=1 setzen. Das Verzeichnis wird mit einem separat "
            "installierten Python geteilt und steht VOR FreeCADs site-packages.",
        )
    else:
        report(OK, "user-site", "nicht wirksam")


# -- FreeCAD ------------------------------------------------------------


def _freecad_module():
    """FreeCAD-Modul, falls dieses Python es laden kann."""
    module = sys.modules.get("FreeCAD")
    if module is not None:
        return module
    try:
        import FreeCAD as module
    except ImportError:
        return None
    return module


def check_freecad():
    try:
        import FreeCAD
    except ImportError:
        report(
            WARN,
            "FreeCAD nicht importierbar",
            "(erwartet, wenn dies die Backend-venv ist)",
            "Fuer die Bruecken-Pruefungen mit FreeCADs Python starten.",
        )
        return None

    version = ".".join(FreeCAD.Version()[:3])
    report(OK, "FreeCAD", version)

    user_dir = FreeCAD.getUserAppDataDir().rstrip("\\/")
    leaf = os.path.basename(user_dir)
    if leaf.startswith("v") and "-" in leaf:
        report(OK, "Benutzerverzeichnis", user_dir)
    else:
        report(
            WARN,
            "Benutzerverzeichnis unversioniert",
            user_dir,
            "FreeCAD 1.1 nutzt versionierte Verzeichnisse (v1-1, mit Bindestrich).",
        )
    return FreeCAD


def check_addon_link(freecad):
    if freecad is None:
        return
    mod_dir = os.path.join(freecad.getUserAppDataDir(), "Mod")
    if not os.path.isdir(mod_dir):
        report(FAIL, "Mod-Verzeichnis fehlt", mod_dir, "scripts/link-addon ausfuehren.")
        return

    candidates = [
        name
        for name in os.listdir(mod_dir)
        if os.path.isfile(os.path.join(mod_dir, name, "package.xml"))
        and "SysML" in name + _read_name(os.path.join(mod_dir, name, "package.xml"))
    ]
    if not candidates:
        report(
            WARN,
            "Addon nicht in Mod/ verlinkt",
            mod_dir,
            "scripts/link-addon ausfuehren -- oder FreeCAD mit "
            '-M "%s" starten.' % BRIDGE,
        )
        return

    path = os.path.join(mod_dir, candidates[0])
    if _is_link(path):
        report(OK, "Addon verlinkt", "%s -> %s" % (candidates[0], os.path.realpath(path)))
    else:
        report(
            WARN,
            "Addon ist eine KOPIE, kein Link",
            path,
            "Verzeichnis loeschen und scripts/link-addon ausfuehren, sonst "
            "bearbeitet ihr eine tote Kopie.",
        )


def _read_name(package_xml):
    try:
        with open(package_xml, "r", encoding="utf-8") as handle:
            return handle.read(400)
    except OSError:
        return ""


def _is_link(path):
    if os.path.islink(path):
        return True
    if os.name == "nt":
        try:
            return bool(os.stat(path, follow_symlinks=False).st_file_attributes & 0x400)
        except (OSError, AttributeError):
            return False
    return False


# -- Vertrag ------------------------------------------------------------


def check_contract():
    if BRIDGE not in sys.path:
        sys.path.insert(0, BRIDGE)
    try:
        from cad_contract.version import CONTRACT_VERSION
    except ImportError as exc:
        report(
            FAIL,
            "cad_contract nicht importierbar",
            exc,
            "Es muss unter bridge/cad_contract liegen; das Backend bindet es "
            "editierbar ueber [tool.uv.sources].",
        )
        return None
    report(OK, "cad_contract", CONTRACT_VERSION)
    return CONTRACT_VERSION


# -- Laufende Bruecke ---------------------------------------------------


def _handshake_path(freecad):
    """Wie das Backend: ohne FreeCAD aus dem OS-Standardpfad (app/config.py)."""
    if freecad is not None:
        return os.path.join(freecad.getUserAppDataDir(), "sysml-cad-platform", "bridge.json")
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", os.path.expanduser("~/AppData/Roaming"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "FreeCAD", "v1-1", "sysml-cad-platform", "bridge.json")


def check_bridge(freecad, contract_version=None):
    path = os.environ.get("BRIDGE_HANDSHAKE") or _handshake_path(freecad)
    if not os.path.isfile(path):
        report(OK, "Bruecke", "nicht gestartet (Normalzustand)")
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        report(WARN, "Handshake-Datei unlesbar", exc, "Datei loeschen: %s" % path)
        return

    if not _pid_alive(data.get("pid")):
        report(
            WARN,
            "Handshake-Datei verwaist",
            "PID %s lebt nicht mehr" % data.get("pid"),
            "Datei loeschen: %s" % path,
        )
        return
    report(OK, "Bruecke", "laeuft, PID %s, Port %s" % (data.get("pid"), data.get("port")))

    running = data.get("contract_version")
    if contract_version and running and running != contract_version:
        report(
            WARN,
            "Laufende Bruecke hat einen anderen Vertrag",
            "Bruecke %s, Repo %s" % (running, contract_version),
            "FreeCAD neu starten -- die Bruecke laedt Codeaenderungen erst dann (CHANGELOG.md).",
        )


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %s" % pid, "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in out.stdout
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def check_ports():
    for port, who in ((8765, "Bruecke"), (8000, "Backend")):
        free = _port_free(port)
        report(OK, "Port %d (%s)" % (port, who), "frei" if free else "belegt")


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


# -- Frontend und Backend ----------------------------------------------


def check_backend_env():
    venv = os.path.join(REPO, "backend", ".venv")
    if os.path.isdir(venv):
        report(OK, "Backend-venv", venv)
    else:
        report(WARN, "Backend-venv fehlt", venv, "scripts/setup ausfuehren (oder: cd backend && uv sync).")


def check_frontend():
    if not os.path.isdir(os.path.join(REPO, "frontend", "node_modules")):
        report(WARN, "Frontend-Abhaengigkeiten fehlen", "", "scripts/setup ausfuehren (oder: cd frontend && pnpm install).")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_status

    state, newest = build_status.status()
    if state == "fresh":
        report(OK, "Oberflaeche gebaut", "aktuell")
    elif state == "stale":
        report(
            WARN,
            "Oberflaeche veraltet",
            "neuer: %s" % os.path.relpath(newest, REPO),
            "scripts/start baut automatisch neu (oder: cd frontend && pnpm build).",
        )
    else:
        report(WARN, "Oberflaeche nicht gebaut", "", "scripts/setup ausfuehren (oder: cd frontend && pnpm build).")


def check_running_backend():
    """Laeuft schon ein Backend auf 8000 -- und ist es unseres?"""
    if _port_free(8000):
        return
    try:
        from urllib.request import urlopen

        with urlopen("http://127.0.0.1:8000/api/status", timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        bridge = data.get("bridge", {})
        report(OK, "Backend laeuft", "Bruecke: %s" % bridge.get("state"))
    except Exception:
        report(
            WARN,
            "Port 8000 belegt, aber nicht von diesem Backend",
            "",
            "Den Prozess auf Port 8000 beenden; das Backend nutzt bewusst einen festen Port.",
        )


# -- Werkzeuge ----------------------------------------------------------


def check_openssl_conf():
    """Eine andere Installation (z. B. PostgreSQL) setzt OPENSSL_CONF auf eine
    fehlende Datei -- node und pnpm brechen dann mit 'OpenSSL configuration error' ab."""
    value = os.environ.get("OPENSSL_CONF")
    if value and not os.path.isfile(value):
        report(
            WARN,
            "OPENSSL_CONF zeigt auf eine fehlende Datei",
            value,
            "Die Skripte in scripts/ leeren die Variable fuer sich; von Hand: OPENSSL_CONF leeren.",
        )


def check_pnpm_version():
    """Das Lockfile ist v9 (pnpm >= 10). Ein aelteres pnpm loest es still neu auf."""
    pnpm = shutil.which("pnpm")
    if not pnpm:
        return
    try:
        env = dict(os.environ)
        if env.get("OPENSSL_CONF") and not os.path.isfile(env["OPENSSL_CONF"]):
            env.pop("OPENSSL_CONF")
        out = subprocess.run([pnpm, "--version"], capture_output=True, text=True, timeout=30, env=env)
        major = int(out.stdout.strip().split(".")[0])
    except Exception:
        report(WARN, "pnpm startet nicht", pnpm, "pnpm neu installieren: npm i -g pnpm@10")
        return
    if major < 10:
        report(
            WARN,
            "pnpm zu alt",
            out.stdout.strip(),
            "Die Skripte weichen auf 'corepack pnpm' aus. Von Hand: 'corepack pnpm ...' "
            "oder pnpm aktualisieren (npm i -g pnpm@10).",
        )
    else:
        report(OK, "pnpm-Version", out.stdout.strip())


def check_node_version():
    node = shutil.which("node")
    if not node:
        return
    try:
        out = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True, timeout=20)
        major, minor = [int(part) for part in out.stdout.strip().split(".")[:2]]
    except Exception:
        return
    # Vite 8 verlangt Node 20.19+ bzw. 22.12+.
    if (major, minor) < (20, 19) or (major == 21) or (major == 22 and minor < 12):
        report(WARN, "Node zu alt fuer Vite 8", "%d.%d" % (major, minor), "Node 22 LTS oder neuer installieren.")
    else:
        report(OK, "Node-Version", "%d.%d" % (major, minor))


def check_tools():
    for tool, fix in (
        ("git", "https://git-scm.com"),
        ("node", "https://nodejs.org (>= 20)"),
        ("pnpm", "npm i -g pnpm@10  (oder corepack, kommt mit node)"),
        ("uv", "https://docs.astral.sh/uv/"),
    ):
        path = shutil.which(tool)
        if path:
            report(OK, tool, path)
        else:
            report(WARN, "%s fehlt" % tool, "", fix)


def main():
    print("SysML-CAD Platform -- Diagnose")
    print("Repo: %s\n" % REPO)

    check_python()
    check_user_site()
    freecad = check_freecad()
    contract = check_contract()
    check_addon_link(freecad)
    check_bridge(freecad, contract)
    check_ports()
    check_running_backend()
    check_tools()
    check_openssl_conf()
    check_node_version()
    check_pnpm_version()
    check_backend_env()
    check_frontend()

    fails = [r for r in _results if r[0] == FAIL]
    warns = [r for r in _results if r[0] == WARN]
    print("\n%d OK, %d Warnungen, %d Fehler" % (len(_results) - len(fails) - len(warns), len(warns), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
