"""The connection to the FreeCAD bridge.

The bridge is a service that comes and goes: FreeCAD gets closed, restarted,
the bridge gets stopped in the dock panel. "Bridge unreachable" is therefore
a NORMAL STATE, not an error. Everything that doesn't need CAD keeps
working.

FOUR STATES, not two:
  unconfigured  no (valid) handshake file -- FreeCAD isn't running or the
                bridge was never started
  unreachable   handshake file present, but nobody answers
  busy          bridge answers, FreeCAD is currently computing (dispatch timeout)
  ok            connected

RE-READ THE HANDSHAKE ON EVERY ATTEMPT. The bridge generates a new token on
every start. Whoever reads the file only once never reconnects after a
FreeCAD restart -- exactly the sequence M5 is meant to prove. A 401 is
therefore a reason to re-read, not to give up.

RESYNC INSTEAD OF REPLAY. Every event carries a session_id and a monotonic seq.
After every (re)connect and on every batch they are compared: new session or
gap in the seq -> the browser has to reload everything. There is deliberately
no event journal.

The bridge's token NEVER leaves this process -- the browser doesn't see it.
"""

import asyncio
import json
import os
import sys

import aiohttp

from app import config
from cad_contract import events as ev
from cad_contract.version import CONTRACT_VERSION

UNCONFIGURED = "unconfigured"
UNREACHABLE = "unreachable"
BUSY = "busy"
OK = "ok"

HANDSHAKE_MAGIC = "sysml-cad-bridge"

_BACKOFF_START_S = 0.5
_BACKOFF_MAX_S = 5.0


class BridgeUnavailable(Exception):
    """The bridge cannot be served right now.

    ``reason`` is machine-readable (the UI translates it),
    ``detail`` is the English plain-text form.
    """

    def __init__(self, state, detail, reason=None):
        super().__init__(detail)
        self.state = state
        self.detail = detail
        self.reason = reason


# -- Handshake ----------------------------------------------------------


def pid_alive(pid):
    """Is the process still alive?

    CAUTION Windows: os.kill(pid, 0) is NOT a probe there but calls
    TerminateProcess -- that would kill FreeCAD. Hence OpenProcess.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False

    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just belongs to someone else


def load_target():
    """(url, token, session_id) of the bridge -- or BridgeUnavailable.

    Called on EVERY attempt. No caching: the token rotates.
    """
    override = config.bridge_override()
    if override is not None:
        url, token = override
        return url, token, None

    path = config.handshake_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise BridgeUnavailable(UNCONFIGURED, "FreeCAD bridge not started", "not_started")
    except (OSError, ValueError):
        raise BridgeUnavailable(UNCONFIGURED, "Handshake file unreadable: %s" % path, "handshake_unreadable")

    if data.get("magic") != HANDSHAKE_MAGIC:
        raise BridgeUnavailable(UNCONFIGURED, "Handshake file has an unknown format", "handshake_format")
    if not pid_alive(data.get("pid")):
        # Orphaned after a crash: the file lives on, FreeCAD doesn't.
        raise BridgeUnavailable(UNCONFIGURED, "FreeCAD bridge not started (orphaned handshake file)", "orphaned_handshake")

    host = data.get("host") or "127.0.0.1"
    if host not in config.LOOPBACK_HOSTS:
        raise BridgeUnavailable(UNCONFIGURED, "Bridge not on loopback -- rejected", "not_loopback")
    return "http://%s:%s" % (host, data["port"]), data["token"], data.get("session_id")


# -- Client -------------------------------------------------------------


class BridgeClient:
    def __init__(self, on_events=None, on_status=None):
        self._on_events = on_events or (lambda events: None)
        self._on_status = on_status or (lambda status: None)
        self._session = None
        self._ws_task = None
        self._running = False

        self.state = UNCONFIGURED
        self.detail = "not connected yet"
        self.reason = "not_connected_yet"
        self.session_id = None
        self.last_seq = None
        self.bridge_contract = None

    # -- State ----------------------------------------------------------

    def status(self):
        return {
            "state": self.state,
            "reason": self.reason,
            "detail": self.detail,
            "session_id": self.session_id,
            "last_seq": self.last_seq,
            "contract": {
                "bridge": self.bridge_contract,
                "backend": CONTRACT_VERSION,
                "match": self.bridge_contract in (None, CONTRACT_VERSION),
            },
        }

    def _set_state(self, state, detail, reason=None):
        if state == self.state and detail == self.detail:
            return
        self.state = state
        self.detail = detail
        self.reason = reason
        self._on_status(self.status())

    # -- Lifecycle ------------------------------------------------------

    async def start(self):
        self._running = True
        self._session = aiohttp.ClientSession()
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self):
        self._running = False
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._session is not None:
            await self._session.close()

    # -- HTTP -----------------------------------------------------------

    async def request(self, method, path, *, query=None, body=None, headers=None,
                      timeout=config.READ_TIMEOUT_S):
        """Forward to the bridge. Returns (status, content_type, bytes).

        On 401 the handshake file is re-read and the request retried ONCE --
        the bridge was probably restarted and has a new token.
        """
        for attempt in (1, 2):
            url, token, _session_id = load_target()  # raises BridgeUnavailable
            send_headers = {"Authorization": "Bearer %s" % token}
            if headers:
                send_headers.update(headers)
            try:
                async with self._session.request(
                    method,
                    url + path,
                    params=query,
                    data=body,
                    headers=send_headers,
                    timeout=aiohttp.ClientTimeout(total=timeout, connect=config.CONNECT_TIMEOUT_S),
                ) as response:
                    payload = await response.read()
                    if response.status == 401 and attempt == 1:
                        continue
                    if response.status == 504:
                        self._set_state(BUSY, "FreeCAD is computing", "computing")
                    elif self.state == BUSY:
                        self._set_state(OK, "connected", "connected")
                    return response.status, response.headers.get("Content-Type"), payload
            except aiohttp.ClientConnectorError:
                self._set_state(UNREACHABLE, "FreeCAD bridge does not respond", "no_response")
                raise BridgeUnavailable(UNREACHABLE, "FreeCAD bridge does not respond", "no_response")
            except asyncio.TimeoutError:
                self._set_state(BUSY, "FreeCAD does not respond in time", "slow")
                raise BridgeUnavailable(BUSY, "FreeCAD does not respond in time", "slow")
        raise BridgeUnavailable(UNREACHABLE, "The bridge rejects the token", "token_rejected")

    # -- Event stream ---------------------------------------------------

    async def _ws_loop(self):
        backoff = _BACKOFF_START_S
        while self._running:
            try:
                url, token, _ = load_target()
            except BridgeUnavailable as exc:
                self._set_state(exc.state, exc.detail, exc.reason)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_S)
                continue

            try:
                async with self._session.ws_connect(
                    url + "/ws",
                    headers={"Authorization": "Bearer %s" % token},
                    heartbeat=20,
                    timeout=aiohttp.ClientWSTimeout(ws_close=5),
                ) as ws:
                    backoff = _BACKOFF_START_S
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            continue
                        self._handle_frame(json.loads(message.data))
            except asyncio.CancelledError:
                raise
            except aiohttp.WSServerHandshakeError as exc:
                # 401: token changed -- re-read on the next iteration.
                self._set_state(UNREACHABLE, "Bridge rejected the login (%s)" % exc.status, "token_rejected")
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                self._set_state(UNREACHABLE, "FreeCAD bridge does not respond", "no_response")
            except Exception as exc:  # never lose the loop
                self._set_state(UNREACHABLE, "Connection error: %s" % type(exc).__name__, "connection_error")

            if self._running and self.state == OK:
                self._set_state(UNREACHABLE, "Connection to the bridge lost", "disconnected")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)

    def _handle_frame(self, frame):
        kind = frame.get("type")
        if kind == ev.HELLO:
            self._handle_hello(frame)
        elif kind == ev.BATCH:
            self._handle_batch(frame.get("events") or [])

    def _handle_hello(self, hello):
        """New connection: did we miss anything?"""
        session_id = hello.get("session_id")
        last_seq = hello.get("last_seq")
        self.bridge_contract = hello.get("contract_version")

        if self.session_id is None:
            reason = "first_connect"
        elif session_id != self.session_id:
            reason = "new_session"      # bridge restarted
        elif last_seq != self.last_seq:
            reason = "missed_events"    # happened while disconnected
        else:
            reason = None

        self.session_id = session_id
        self.last_seq = last_seq

        detail, status_reason = "connected", "connected"
        if not self.status()["contract"]["match"]:
            status_reason = "contract_mismatch"
            detail = (
                "connected, but the contract version differs (bridge %s, backend %s) -- "
                "see CHANGELOG.md" % (self.bridge_contract, CONTRACT_VERSION)
            )
        self._set_state(OK, detail, status_reason)

        if reason is not None:
            self._on_events([self._resync(reason)])

    def _handle_batch(self, events):
        """Forward events and detect gaps."""
        gap = False
        for event in events:
            seq = event.get("seq")
            if seq is None:
                continue  # cad.resync after overflow carries no seq
            if self.last_seq is not None and seq != self.last_seq + 1:
                gap = True
            self.last_seq = seq

        self._on_events(events)
        if gap:
            self._on_events([self._resync("sequence_gap")])

    def _resync(self, reason):
        return {"type": ev.RESYNC, "reason": reason, "session_id": self.session_id}
