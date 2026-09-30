"""Token, handshake file and origin check.

The bridge runs only on 127.0.0.1 and is never hosted. The real attack
vector exists nonetheless: any web page in the user's browser can send
requests to localhost. Two small measures are enough to counter it:

  * The token is required EXCLUSIVELY in the Authorization header -- also
    during the WebSocket handshake. Browsers cannot set headers with
    ``new WebSocket()``, so the bridge WS is structurally unreachable for
    web attackers. No query parameter: that ends up in logs.
  * If an Origin header is present, it must be on the allowlist. If it is
    missing entirely (curl, tests, the backend), the request is let through.

Additionally a Host check against DNS rebinding: there the request is
same-origin and carries no Origin at all, so an Origin check fundamentally
does not help.
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

#: Where browser requests may come from. The backend itself sends no Origin.
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
    """Constant-time comparison; None/empty always fails."""
    if not expected or not presented:
        return False
    return hmac.compare_digest(str(expected), str(presented))


def bearer_from_header(value):
    """Extract ``Authorization: Bearer <token>``, otherwise None."""
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def origin_allowed(origin):
    """A missing Origin is allowed (curl/backend), a foreign one is not."""
    if not origin:
        return True
    return origin.rstrip("/") in ALLOWED_ORIGINS


def host_allowed(host_header):
    """Accept only loopback names -- a second, independent check."""
    if not host_header:
        return True
    hostname = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else host_header.split("]")[0] + "]"
    return hostname in ALLOWED_HOSTNAMES


# -- Handshake file -----------------------------------------------------


def handshake_dir():
    return os.path.join(FreeCAD.getUserAppDataDir(), HANDSHAKE_DIRNAME)


def handshake_path():
    return os.path.join(handshake_dir(), HANDSHAKE_FILENAME)


def write_handshake(port, token, session_id):
    """Write atomically: .tmp + os.replace, mode 0600.

    The backend would treat a half-written JSON as "broken" and go into
    backoff -- so never write directly to the target file.
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
        pass  # no effect on Windows, no reason to fail
    _replace_with_retry(tmp, target)
    return target


def _replace_with_retry(src, dst, attempts=50):
    """os.replace that briefly waits for readers on Windows.

    The backend reads bridge.json on EVERY connection attempt. If it has the
    file open at the same moment, Windows refuses the replace with
    PermissionError -- the bridge start then failed at random.
    Found in the M5 end-to-end test.
    """
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(src, dst)


def read_handshake():
    """Read the handshake file; None if it is missing or unusable."""
    try:
        with open(handshake_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if data.get("magic") != MAGIC:
        return None
    return data


def remove_handshake(session_id):
    """Delete only OUR OWN file.

    Otherwise a second FreeCAD instance, when exiting, removes the file of the
    still-running first one, and the backend loses the connection for no reason.
    """
    data = read_handshake()
    if data is None or data.get("session_id") != session_id:
        return False
    try:
        os.remove(handshake_path())
        return True
    except OSError:
        return False
