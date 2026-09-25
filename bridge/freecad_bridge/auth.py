"""Token, Handshake-Datei und Herkunftspruefung.

Die Bruecke laeuft nur auf 127.0.0.1 und wird nie gehostet. Der reale
Angriffsvektor ist trotzdem vorhanden: jede Webseite im Browser des Nutzers
kann Requests an localhost schicken. Zwei kleine Massnahmen reichen dagegen:

  * Das Token wird AUSSCHLIESSLICH im Authorization-Header verlangt -- auch
    beim WebSocket-Handshake. Browser koennen bei ``new WebSocket()`` keine
    Header setzen, damit ist der Bruecken-WS fuer Web-Angreifer strukturell
    unerreichbar. Kein Query-Parameter: der landet in Logs.
  * Ist ein Origin-Header vorhanden, muss er in der Allowlist stehen. Fehlt er
    ganz (curl, Tests, das Backend), wird durchgelassen.

Zusaetzlich eine Host-Pruefung gegen DNS-Rebinding: dort ist die Anfrage
same-origin und traegt gar keinen Origin, eine Origin-Pruefung hilft also
prinzipiell nicht.
"""

import hmac
import json
import os
import secrets
import time

import FreeCAD

from cad_contract.version import CONTRACT_VERSION

MAGIC = "sysml-cad-bridge"
HANDSHAKE_DIRNAME = "sysml-cad-platform"
HANDSHAKE_FILENAME = "bridge.json"

#: Woher Browser-Anfragen kommen duerfen. Das Backend selbst sendet keinen Origin.
ALLOWED_ORIGINS = frozenset(
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
)

ALLOWED_HOSTNAMES = frozenset(["127.0.0.1", "localhost", "::1", "[::1]"])


def new_token():
    return secrets.token_urlsafe(32)


def token_matches(expected, presented):
    """Zeitkonstanter Vergleich; None/leer schlaegt immer fehl."""
    if not expected or not presented:
        return False
    return hmac.compare_digest(str(expected), str(presented))


def bearer_from_header(value):
    """``Authorization: Bearer <token>`` auslesen, sonst None."""
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def origin_allowed(origin):
    """Fehlender Origin ist erlaubt (curl/Backend), ein fremder nicht."""
    if not origin:
        return True
    return origin.rstrip("/") in ALLOWED_ORIGINS


def host_allowed(host_header):
    """Nur Loopback-Namen akzeptieren -- zweite, unabhaengige Pruefung."""
    if not host_header:
        return True
    hostname = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else host_header.split("]")[0] + "]"
    return hostname in ALLOWED_HOSTNAMES


# -- Handshake-Datei ----------------------------------------------------


def handshake_dir():
    return os.path.join(FreeCAD.getUserAppDataDir(), HANDSHAKE_DIRNAME)


def handshake_path():
    return os.path.join(handshake_dir(), HANDSHAKE_FILENAME)


def write_handshake(port, token, session_id):
    """Atomar schreiben: .tmp + os.replace, Modus 0600.

    Ein halb geschriebenes JSON wuerde das Backend als "kaputt" werten und in
    Backoff gehen -- deshalb nie direkt in die Zieldatei schreiben.
    """
    directory = handshake_dir()
    if not os.path.isdir(directory):
        os.makedirs(directory)

    payload = {
        "magic": MAGIC,
        "pid": os.getpid(),
        "started_at": time.time(),
        "host": "127.0.0.1",
        "port": port,
        "token": token,
        "session_id": session_id,
        "contract_version": CONTRACT_VERSION,
    }

    target = handshake_path()
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # unter Windows ohne Wirkung, kein Grund zu scheitern
    os.replace(tmp, target)
    return target


def read_handshake():
    """Handshake-Datei lesen; None, wenn sie fehlt oder unbrauchbar ist."""
    try:
        with open(handshake_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if data.get("magic") != MAGIC:
        return None
    return data


def remove_handshake(session_id):
    """Nur die EIGENE Datei loeschen.

    Sonst raeumt eine zweite FreeCAD-Instanz beim Beenden die Datei der noch
    laufenden ersten weg, und das Backend verliert grundlos die Verbindung.
    """
    data = read_handshake()
    if data is None or data.get("session_id") != session_id:
        return False
    try:
        os.remove(handshake_path())
        return True
    except OSError:
        return False
