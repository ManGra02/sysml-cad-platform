"""Hardening a service that is never hosted.

The real attack vector: ANY web page the user has open can send requests
to localhost. Especially ``new WebSocket("ws://127.0.0.1:8000/ws")``
-- WebSockets have no same-origin policy, and without a check any
neighbouring tab could read along the complete model stream.

Three checks, each against a different attack:
  1. Origin allowlist  -- foreign sites (CSRF, WebSocket hijacking)
  2. Host allowlist    -- DNS rebinding: there the request is same-origin and
                          carries no foreign Origin at all; only the Host gives it away
  3. WebSocket Origin BEFORE accept()

DELIBERATELY NO CORSMiddleware: as soon as someone adds allow_origins=["*"],
the preflight protection for PATCH/DELETE goes away too. The browser talks
same-origin to the backend -- CORS is simply not needed.

No browser token: the boundary is loopback + Origin + Host.
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
    """A missing Origin is allowed (curl, tests), a foreign one is not."""
    if not origin:
        return True
    return origin.rstrip("/") in config.allowed_origins()


def _forbidden(code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=403)


class LocalOnlyMiddleware:
    """ASGI middleware for HTTP and WebSocket alike."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}

        if not _host_ok(headers.get("host")):
            return await self._reject(scope, receive, send, "forbidden_host", "Forbidden Host header")

        origin = headers.get("origin")
        if scope["type"] == "websocket":
            # Browsers ALWAYS send an Origin for WebSockets -- so it may be
            # required here. Without an Origin the request isn't from a browser.
            if origin is not None and not origin_ok(origin):
                return await self._reject(scope, receive, send, "forbidden_origin", "Forbidden origin")
        elif not origin_ok(origin):
            return await self._reject(scope, receive, send, "forbidden_origin", "Forbidden origin")

        return await self.app(scope, receive, send)

    async def _reject(self, scope, receive, send, code, message):
        if scope["type"] == "websocket":
            # Close before accept(): 1008 = Policy Violation
            await send({"type": "websocket.close", "code": 1008, "reason": code})
            return
        response = _forbidden(code, message)
        await response(scope, receive, send)
