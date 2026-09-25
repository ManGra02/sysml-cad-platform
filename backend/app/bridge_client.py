"""Die Verbindung zur FreeCAD-Bruecke.

Die Bruecke ist ein Dienst, der kommt und geht: FreeCAD wird geschlossen, neu
gestartet, die Bruecke im Dock-Panel gestoppt. "Bruecke nicht erreichbar" ist
deshalb ein NORMALZUSTAND, kein Fehler. Alles, was kein CAD braucht,
funktioniert weiter.

VIER ZUSTAENDE, nicht zwei:
  unconfigured  keine (gueltige) Handshake-Datei -- FreeCAD laeuft nicht oder
                die Bruecke wurde nie gestartet
  unreachable   Handshake-Datei vorhanden, aber niemand antwortet
  busy          Bruecke antwortet, FreeCAD rechnet gerade (Dispatch-Timeout)
  ok            verbunden

HANDSHAKE BEI JEDEM VERSUCH NEU LESEN. Die Bruecke erzeugt bei jedem Start ein
neues Token. Wer die Datei nur einmal liest, verbindet sich nach einem
FreeCAD-Neustart nie wieder -- genau der Ablauf, den M5 beweisen soll. Ein 401
ist deshalb Anlass zum Neulesen, nicht zum Aufgeben.

RESYNC STATT REPLAY. Jedes Ereignis traegt session_id und eine monotone seq.
Nach jedem (Re-)Connect und bei jedem Batch wird verglichen: neue Sitzung oder
Luecke in der seq -> der Browser muss alles neu laden. Ein Ereignis-Journal
gibt es bewusst nicht.

Das Token der Bruecke verlaesst diesen Prozess NIE -- der Browser sieht es nicht.
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
    """Die Bruecke kann gerade nicht bedient werden."""

    def __init__(self, state, detail):
        super().__init__(detail)
        self.state = state
        self.detail = detail


# -- Handshake ----------------------------------------------------------


def pid_alive(pid):
    """Lebt der Prozess noch?

    ACHTUNG Windows: os.kill(pid, 0) ist dort KEINE Probe, sondern ruft
    TerminateProcess -- das wuerde FreeCAD beenden. Deshalb OpenProcess.
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
        return True  # existiert, gehoert nur jemand anderem


def load_target():
    """(url, token, session_id) der Bruecke -- oder BridgeUnavailable.

    Wird bei JEDEM Versuch aufgerufen. Kein Caching: das Token rotiert.
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
        raise BridgeUnavailable(UNCONFIGURED, "FreeCAD-Bruecke nicht gestartet")
    except (OSError, ValueError):
        raise BridgeUnavailable(UNCONFIGURED, "Handshake-Datei unlesbar: %s" % path)

    if data.get("magic") != HANDSHAKE_MAGIC:
        raise BridgeUnavailable(UNCONFIGURED, "Handshake-Datei unbekannten Formats")
    if not pid_alive(data.get("pid")):
        # Verwaist nach einem Absturz: die Datei lebt, FreeCAD nicht.
        raise BridgeUnavailable(UNCONFIGURED, "FreeCAD-Bruecke nicht gestartet (verwaiste Handshake-Datei)")

    host = data.get("host") or "127.0.0.1"
    if host not in config.LOOPBACK_HOSTS:
        raise BridgeUnavailable(UNCONFIGURED, "Bruecke nicht auf Loopback -- abgelehnt")
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
        self.detail = "noch nicht verbunden"
        self.session_id = None
        self.last_seq = None
        self.bridge_contract = None

    # -- Zustand --------------------------------------------------------

    def status(self):
        return {
            "state": self.state,
            "detail": self.detail,
            "session_id": self.session_id,
            "last_seq": self.last_seq,
            "contract": {
                "bridge": self.bridge_contract,
                "backend": CONTRACT_VERSION,
                "match": self.bridge_contract in (None, CONTRACT_VERSION),
            },
        }

    def _set_state(self, state, detail):
        if state == self.state and detail == self.detail:
            return
        self.state = state
        self.detail = detail
        self._on_status(self.status())

    # -- Lebenszyklus ---------------------------------------------------

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
        """An die Bruecke weiterreichen. Liefert (status, content_type, bytes).

        Bei 401 wird die Handshake-Datei neu gelesen und EINMAL wiederholt --
        die Bruecke wurde vermutlich neu gestartet und hat ein neues Token.
        """
        for attempt in (1, 2):
            url, token, _session_id = load_target()  # wirft BridgeUnavailable
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
                        self._set_state(BUSY, "FreeCAD rechnet gerade")
                    elif self.state == BUSY:
                        self._set_state(OK, "verbunden")
                    return response.status, response.headers.get("Content-Type"), payload
            except aiohttp.ClientConnectorError:
                self._set_state(UNREACHABLE, "FreeCAD-Bruecke antwortet nicht")
                raise BridgeUnavailable(UNREACHABLE, "FreeCAD-Bruecke antwortet nicht")
            except asyncio.TimeoutError:
                self._set_state(BUSY, "FreeCAD antwortet nicht rechtzeitig")
                raise BridgeUnavailable(BUSY, "FreeCAD antwortet nicht rechtzeitig")
        raise BridgeUnavailable(UNREACHABLE, "Token wird von der Bruecke abgelehnt")

    # -- Ereignisstrom --------------------------------------------------

    async def _ws_loop(self):
        backoff = _BACKOFF_START_S
        while self._running:
            try:
                url, token, _ = load_target()
            except BridgeUnavailable as exc:
                self._set_state(exc.state, exc.detail)
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
                # 401: Token gewechselt -- beim naechsten Durchlauf neu lesen.
                self._set_state(UNREACHABLE, "Anmeldung an der Bruecke abgelehnt (%s)" % exc.status)
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                self._set_state(UNREACHABLE, "FreeCAD-Bruecke antwortet nicht")
            except Exception as exc:  # nie die Schleife verlieren
                self._set_state(UNREACHABLE, "Verbindungsfehler: %s" % type(exc).__name__)

            if self._running and self.state == OK:
                self._set_state(UNREACHABLE, "Verbindung zur Bruecke getrennt")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)

    def _handle_frame(self, frame):
        kind = frame.get("type")
        if kind == ev.HELLO:
            self._handle_hello(frame)
        elif kind == ev.BATCH:
            self._handle_batch(frame.get("events") or [])

    def _handle_hello(self, hello):
        """Neue Verbindung: haben wir etwas verpasst?"""
        session_id = hello.get("session_id")
        last_seq = hello.get("last_seq")
        self.bridge_contract = hello.get("contract_version")

        if self.session_id is None:
            reason = "first_connect"
        elif session_id != self.session_id:
            reason = "new_session"      # Bruecke neu gestartet
        elif last_seq != self.last_seq:
            reason = "missed_events"    # waehrend der Trennung passiert
        else:
            reason = None

        self.session_id = session_id
        self.last_seq = last_seq

        detail = "verbunden"
        if not self.status()["contract"]["match"]:
            detail = (
                "verbunden, aber Vertragsversion weicht ab (Bruecke %s, Backend %s) -- "
                "siehe CHANGELOG.md" % (self.bridge_contract, CONTRACT_VERSION)
            )
        self._set_state(OK, detail)

        if reason is not None:
            self._on_events([self._resync(reason)])

    def _handle_batch(self, events):
        """Ereignisse weiterreichen und Luecken erkennen."""
        gap = False
        for event in events:
            seq = event.get("seq")
            if seq is None:
                continue  # cad.resync nach Ueberlauf traegt keine seq
            if self.last_seq is not None and seq != self.last_seq + 1:
                gap = True
            self.last_seq = seq

        self._on_events(events)
        if gap:
            self._on_events([self._resync("sequence_gap")])

    def _resync(self, reason):
        return {"type": ev.RESYNC, "reason": reason, "session_id": self.session_id}
