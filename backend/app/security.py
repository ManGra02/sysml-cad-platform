"""Absicherung eines Dienstes, der nie gehostet wird.

Der reale Angriffsvektor: JEDE Webseite, die der Nutzer offen hat, kann
Requests an localhost schicken. Besonders ``new WebSocket("ws://127.0.0.1:8000/ws")``
-- WebSockets kennen keine Same-Origin-Policy, und ohne Pruefung laese ein
beliebiger Nachbar-Tab den vollstaendigen Modellstrom mit.

Drei Pruefungen, jede fuer einen anderen Angriff:
  1. Origin-Allowlist  -- fremde Seiten (CSRF, WebSocket-Hijacking)
  2. Host-Allowlist    -- DNS-Rebinding: dort ist die Anfrage same-origin und
                          traegt gar keinen fremden Origin; nur der Host verraet sie
  3. WebSocket-Origin VOR accept()

BEWUSST KEINE CORSMiddleware: sobald jemand allow_origins=["*"] einbaut, faellt
auch der Preflight-Schutz fuer PATCH/DELETE. Der Browser spricht same-origin mit
dem Backend -- CORS wird schlicht nicht gebraucht.

Kein Browser-Token: die Grenze ist Loopback + Origin + Host.
"""

from starlette.responses import JSONResponse

from app import config


def _host_ok(host_header):
    if not host_header:
        return True
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.rsplit(":", 1)[0]
    return host in config.allowed_hosts()


def origin_ok(origin):
    """Fehlender Origin ist erlaubt (curl, Tests), ein fremder nicht."""
    if not origin:
        return True
    return origin.rstrip("/") in config.allowed_origins()


def _forbidden(code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=403)


class LocalOnlyMiddleware:
    """ASGI-Middleware fuer HTTP und WebSocket gleichermassen."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}

        if not _host_ok(headers.get("host")):
            return await self._reject(scope, receive, send, "forbidden_host", "Unerlaubter Host-Header")

        origin = headers.get("origin")
        if scope["type"] == "websocket":
            # Browser senden beim WebSocket IMMER einen Origin -- hier darf er
            # verlangt werden. Ohne Origin kommt die Anfrage nicht aus einem Browser.
            if origin is not None and not origin_ok(origin):
                return await self._reject(scope, receive, send, "forbidden_origin", "Unerlaubte Herkunft")
        elif not origin_ok(origin):
            return await self._reject(scope, receive, send, "forbidden_origin", "Unerlaubte Herkunft")

        return await self.app(scope, receive, send)

    async def _reject(self, scope, receive, send, code, message):
        if scope["type"] == "websocket":
            # Vor accept() schliessen: 1008 = Policy Violation
            await send({"type": "websocket.close", "code": 1008, "reason": code})
            return
        response = _forbidden(code, message)
        await response(scope, receive, send)
