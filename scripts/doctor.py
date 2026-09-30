"""Diagnostics for the development environment.

Runs in BOTH Pythons -- FreeCAD's bundled one and the backend venv -- and
checks what experience shows tends to go wrong. Every message names the fix.

The reason for this script: "bridge not connected" is a normal state
and reveals no cause. Without doctor, every person on the team spends the same
half hour searching.

Usage:
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


# -- Python and environment ---------------------------------------------


def check_python():
    version = "%d.%d.%d" % sys.version_info[:3]
    in_freecad = _freecad_module() is not None
    report(OK, "Python", "%s (%s)" % (version, "FreeCAD" if in_freecad else "external"))

    if in_freecad and sys.version_info[:2] != (3, 11):
        report(
            WARN,
            "Python version in FreeCAD",
            version,
            "cad_contract must match 3.11; do not use PEP 695.",
        )


def check_user_site():
    """The user site shadows FreeCAD's bundled packages."""
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
            "user-site active",
            user_site,
            "Set PYTHONNOUSERSITE=1. The directory is shared with a separately "
            "installed Python and comes BEFORE FreeCAD's site-packages.",
        )
    else:
        report(OK, "user-site", "not in effect")


# -- FreeCAD ------------------------------------------------------------


def _freecad_module():
    """The FreeCAD module, if this Python can load it."""
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
            "FreeCAD not importable",
            "(expected if this is the backend venv)",
            "Run with FreeCAD's Python for the bridge checks.",
        )
        return None

    version = ".".join(FreeCAD.Version()[:3])
    report(OK, "FreeCAD", version)

    user_dir = FreeCAD.getUserAppDataDir().rstrip("\\/")
    leaf = os.path.basename(user_dir)
    if leaf.startswith("v") and "-" in leaf:
        report(OK, "User directory", user_dir)
    else:
        report(
            WARN,
            "User directory unversioned",
            user_dir,
            "FreeCAD 1.1 uses versioned directories (v1-1, with a hyphen).",
        )
    return FreeCAD


def check_addon_link(freecad):
    if freecad is None:
        return
    mod_dir = os.path.join(freecad.getUserAppDataDir(), "Mod")
    if not os.path.isdir(mod_dir):
        report(FAIL, "Mod directory missing", mod_dir, "Run scripts/link-addon.")
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
            "Addon not linked into Mod/",
            mod_dir,
            "Run scripts/link-addon -- or start FreeCAD with "
            '-M "%s".' % BRIDGE,
        )
        return

    path = os.path.join(mod_dir, candidates[0])
    if _is_link(path):
        report(OK, "Addon linked", "%s -> %s" % (candidates[0], os.path.realpath(path)))
    else:
        report(
            WARN,
            "Addon is a COPY, not a link",
            path,
            "Delete the directory and run scripts/link-addon, otherwise "
            "you are editing a dead copy.",
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


# -- Contract -----------------------------------------------------------


def check_contract():
    if BRIDGE not in sys.path:
        sys.path.insert(0, BRIDGE)
    try:
        from cad_contract.version import CONTRACT_VERSION
    except ImportError as exc:
        report(
            FAIL,
            "cad_contract not importable",
            exc,
            "It must live under bridge/cad_contract; the backend includes it "
            "as editable via [tool.uv.sources].",
        )
        return None
    report(OK, "cad_contract", CONTRACT_VERSION)
    return CONTRACT_VERSION


# -- Running bridge -----------------------------------------------------


def _handshake_path(freecad):
    """Like the backend: without FreeCAD, from the OS default path (app/config.py)."""
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
        report(OK, "Bridge", "not started (normal state)")
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        report(WARN, "Handshake file unreadable", exc, "Delete the file: %s" % path)
        return

    if not _pid_alive(data.get("pid")):
        report(
            WARN,
            "Handshake file orphaned",
            "PID %s is no longer alive" % data.get("pid"),
            "Delete the file: %s" % path,
        )
        return
    report(OK, "Bridge", "running, PID %s, port %s" % (data.get("pid"), data.get("port")))

    running = data.get("contract_version")
    if contract_version and running and running != contract_version:
        report(
            WARN,
            "Running bridge has a different contract",
            "bridge %s, repo %s" % (running, contract_version),
            "Restart FreeCAD -- the bridge only loads code changes then (CHANGELOG.md).",
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
    for port, who in ((8765, "Bridge"), (8000, "Backend")):
        free = _port_free(port)
        report(OK, "Port %d (%s)" % (port, who), "free" if free else "in use")


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


# -- Frontend and backend ----------------------------------------------


def check_backend_env():
    venv = os.path.join(REPO, "backend", ".venv")
    if os.path.isdir(venv):
        report(OK, "Backend venv", venv)
    else:
        report(WARN, "Backend venv missing", venv, "Run scripts/setup (or: cd backend && uv sync).")


def check_frontend():
    if not os.path.isdir(os.path.join(REPO, "frontend", "node_modules")):
        report(WARN, "Frontend dependencies missing", "", "Run scripts/setup (or: cd frontend && pnpm install).")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_status

    state, newest = build_status.status()
    if state == "fresh":
        report(OK, "UI built", "up to date")
    elif state == "stale":
        report(
            WARN,
            "UI stale",
            "newer: %s" % os.path.relpath(newest, REPO),
            "scripts/start rebuilds automatically (or: cd frontend && pnpm build).",
        )
    else:
        report(WARN, "UI not built", "", "Run scripts/setup (or: cd frontend && pnpm build).")


def check_running_backend():
    """Is a backend already running on 8000 -- and is it ours?"""
    if _port_free(8000):
        return
    try:
        from urllib.request import urlopen

        with urlopen("http://127.0.0.1:8000/api/status", timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        bridge = data.get("bridge", {})
        report(OK, "Backend running", "bridge: %s" % bridge.get("state"))
    except Exception:
        report(
            WARN,
            "Port 8000 in use, but not by this backend",
            "",
            "Stop the process on port 8000; the backend deliberately uses a fixed port.",
        )


# -- Tools --------------------------------------------------------------


def check_openssl_conf():
    """Another installation (e.g. PostgreSQL) sets OPENSSL_CONF to a
    missing file -- node and pnpm then abort with 'OpenSSL configuration error'."""
    value = os.environ.get("OPENSSL_CONF")
    if value and not os.path.isfile(value):
        report(
            WARN,
            "OPENSSL_CONF points to a missing file",
            value,
            "The scripts in scripts/ clear the variable for themselves; manually: clear OPENSSL_CONF.",
        )


def check_pnpm_version():
    """The lockfile is v9 (pnpm >= 10). An older pnpm silently re-resolves it."""
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
        report(WARN, "pnpm does not start", pnpm, "Reinstall pnpm: npm i -g pnpm@10")
        return
    if major < 10:
        report(
            WARN,
            "pnpm too old",
            out.stdout.strip(),
            "The scripts fall back to 'corepack pnpm'. Manually: 'corepack pnpm ...' "
            "or update pnpm (npm i -g pnpm@10).",
        )
    else:
        report(OK, "pnpm version", out.stdout.strip())


def check_node_version():
    node = shutil.which("node")
    if not node:
        return
    try:
        out = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True, timeout=20)
        major, minor = [int(part) for part in out.stdout.strip().split(".")[:2]]
    except Exception:
        return
    # Vite 8 requires Node 20.19+ or 22.12+.
    if (major, minor) < (20, 19) or (major == 21) or (major == 22 and minor < 12):
        report(WARN, "Node too old for Vite 8", "%d.%d" % (major, minor), "Install Node 22 LTS or newer.")
    else:
        report(OK, "Node version", "%d.%d" % (major, minor))


def check_tools():
    for tool, fix in (
        ("git", "https://git-scm.com"),
        ("node", "https://nodejs.org (>= 20)"),
        ("pnpm", "npm i -g pnpm@10  (or corepack, ships with node)"),
        ("uv", "https://docs.astral.sh/uv/"),
    ):
        path = shutil.which(tool)
        if path:
            report(OK, tool, path)
        else:
            report(WARN, "%s missing" % tool, "", fix)


def main():
    print("SysML-CAD Platform -- Diagnostics")
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
    print("\n%d OK, %d warnings, %d errors" % (len(_results) - len(fails) - len(warns), len(warns), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
