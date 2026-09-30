"""M5: Backend -- connection, resync, pass-through, hardening.

Everything against a mock bridge, without FreeCAD.
"""

import asyncio
import json
import os
import subprocess
import sys

import aiohttp

from app import bridge_client
from conftest import BROWSER_ORIGIN, BrowserClient, MockBridge, wait_for


# -- Connection states ------------------------------------------------


async def test_ohne_handshake_unconfigured(backend):
    status = await backend.status()
    assert status["state"] == "unconfigured"


async def test_cad_route_ohne_bruecke_ist_503_mit_zustand(backend):
    code, body = await backend.get("/api/cad/documents")
    assert code == 503
    assert body["error"]["code"] == "bridge_unconfigured"


async def test_verbindet_sich_mit_der_bruecke(bridge, backend):
    await wait_for(lambda: backend.state.bridge.state == "ok")
    status = await backend.status()
    assert status["session_id"] == bridge.session_id
    assert status["contract"]["match"] is True


async def test_bruecke_startet_spaeter(handshake, backend):
    """FreeCAD is started AFTER the backend -- the normal case."""
    assert (await backend.status())["state"] == "unconfigured"
    mock = MockBridge(str(handshake))
    await mock.start()
    try:
        await wait_for(lambda: backend.state.bridge.state == "ok", timeout=10)
    finally:
        await mock.stop()


async def test_bruecke_verschwindet(bridge, backend, browser):
    await wait_for(lambda: backend.state.bridge.state == "ok")
    await bridge.stop(remove_handshake=False)
    # Wait for the BROWSER, not just for the backend state -- otherwise the
    # WebSocket message may still be in flight.
    await wait_for(lambda: any(s["state"] != "ok" for s in browser.statuses()))


async def test_verwaiste_handshake_datei(handshake, backend):
    """After a crash the file lives on, FreeCAD doesn't."""
    mock = MockBridge(str(handshake))
    await mock.start()
    mock.write_handshake(pid=_dead_pid())
    try:
        await wait_for(lambda: backend.state.bridge.reason == "orphaned_handshake", timeout=10)
        status = await backend.status()
        assert status["state"] == "unconfigured"
        # And above all: HTTP doesn't even try against a dead PID.
        code, body = await backend.get("/api/cad/documents")
        assert code == 503 and body["error"]["detail"]["reason"] == "orphaned_handshake"
    finally:
        await mock.stop()


def _dead_pid():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_pid_probe_beendet_keinen_prozess():
    """os.kill(pid, 0) would be TerminateProcess on Windows -- that must not happen."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert bridge_client.pid_alive(process.pid) is True
        assert process.poll() is None, "The probe killed the process!"
    finally:
        process.kill()
        process.wait()
    assert bridge_client.pid_alive(process.pid) is False


# -- Resync ------------------------------------------------------------


async def test_spaeter_verbundener_browser_kennt_den_zustand(bridge, backend):
    """A browser that connects AFTER the bridge connection has missed the
    first_connect resync. It doesn't need it: it loads everything on open anyway,
    and the hello tells it the current bridge state."""
    await wait_for(lambda: backend.state.bridge.state == "ok")
    client = await BrowserClient(backend.url).connect()
    try:
        await wait_for(lambda: client.frames)
        hello = client.frames[0]
        assert hello["type"] == "hello"
        assert hello["bridge"]["state"] == "ok"
        assert hello["bridge"]["session_id"] == bridge.session_id
    finally:
        await client.close()


async def test_ereignisse_werden_weitergereicht(bridge, backend, browser):
    await wait_for(lambda: bridge.ws_count == 1)
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "Box", "props": ["Length"]}])
    await wait_for(lambda: browser.events("cad.changed"))
    event = browser.events("cad.changed")[0]
    assert event["obj"] == "Box" and event["seq"] == 1


async def test_luecke_in_seq_loest_resync_aus(bridge, backend, browser):
    await wait_for(lambda: bridge.ws_count == 1)
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "A", "props": []}])
    bridge.happened_while_nobody_listened(3)
    await bridge.push([{"type": "cad.changed", "doc": "Doc", "obj": "B", "props": []}])
    await wait_for(lambda: any(e["reason"] == "sequence_gap" for e in browser.events("cad.resync")))


async def test_verpasste_ereignisse_waehrend_trennung(bridge, backend, browser):
    """Bridge briefly gone, something happens meanwhile -> resync on reconnect."""
    await wait_for(lambda: bridge.ws_count == 1)
    await bridge.stop(remove_handshake=False)
    await wait_for(lambda: backend.state.bridge.state != "ok")

    bridge.happened_while_nobody_listened(3)   # e.g. three objects created
    await bridge.start(new_session=False)
    await wait_for(lambda: any(e["reason"] == "missed_events" for e in browser.events("cad.resync")),
                   timeout=10)


async def test_neustart_der_bruecke_rotiert_token_und_sitzung(bridge, backend, browser):
    """The backend has to re-read the handshake file on EVERY attempt."""
    await wait_for(lambda: backend.state.bridge.state == "ok")
    old_session = bridge.session_id

    await bridge.stop()
    await bridge.start(new_session=True)          # new token, new session
    await wait_for(lambda: backend.state.bridge.session_id == bridge.session_id, timeout=10)
    assert bridge.session_id != old_session
    await wait_for(lambda: any(e["reason"] == "new_session" for e in browser.events("cad.resync")))

    code, body = await backend.get("/api/cad/documents")
    assert code == 200, "HTTP must work with the new token"


# -- Pass-through -------------------------------------------------------


async def test_get_wird_weitergereicht(bridge, backend):
    code, body = await backend.get("/api/cad/documents")
    assert code == 200
    assert body["active"] == "Doc"


async def test_query_und_unicode_namen(bridge, backend):
    path = "/api/cad/documents/Doc/objects/%C3%84u%C3%9Feres?include=geometry"
    code, body = await backend.get(path)
    assert code == 200
    assert body["name"] == "Äußeres"
    assert body["query"] == {"include": "geometry"}


async def test_patch_mit_request_id(bridge, backend):
    async with backend.http.patch(
        backend.url + "/api/cad/documents/Doc/objects/Box",
        json={"Length": "40 mm"},
        headers={"X-Request-Id": "req-42"},
    ) as response:
        body = await response.json()
    assert body["received"] == {"Length": "40 mm"}
    assert body["request_id"] == "req-42"


async def test_recompute_route(bridge, backend):
    async with backend.http.post(backend.url + "/api/cad/documents/Doc/recompute") as response:
        assert response.status == 200


async def test_token_verlaesst_das_backend_nie(bridge, backend):
    code, status = await backend.get("/api/status")
    assert bridge.token not in json.dumps(status)

    browser = BrowserClient(backend.url)
    await browser.connect()
    try:
        await wait_for(lambda: browser.frames)
        assert bridge.token not in json.dumps(browser.frames)
    finally:
        await browser.close()


async def test_browser_authorization_wird_nicht_weitergereicht(bridge, backend):
    await backend.get("/api/cad/documents", headers={"Authorization": "Bearer evil"})
    forwarded = [r for r in bridge.requests if r["path"] == "/api/cad/documents"][-1]
    assert forwarded["headers"]["Authorization"] == "Bearer %s" % bridge.token


# -- Hardening ----------------------------------------------------------


async def test_fremder_origin_403(bridge, backend):
    async with backend.http.get(backend.url + "/api/status",
                                headers={"Origin": "http://evil.example"}) as response:
        assert response.status == 403


async def test_fremder_origin_auch_bei_post(bridge, backend):
    """A bodyless POST needs no preflight -- without the check it would go through."""
    async with backend.http.post(backend.url + "/api/cad/documents/Doc/recompute",
                                 headers={"Origin": "http://evil.example"}) as response:
        assert response.status == 403
    assert not [r for r in bridge.requests if r["path"].endswith("/recompute")]


async def test_fremder_host_403(backend):
    async with backend.http.get(backend.url + "/api/status",
                                headers={"Host": "attacker.example"}) as response:
        assert response.status == 403


async def test_websocket_von_fremder_seite_abgewiesen(backend):
    session = aiohttp.ClientSession()
    try:
        try:
            ws = await session.ws_connect(backend.url + "/ws",
                                          headers={"Origin": "http://evil.example"})
            message = await ws.receive(timeout=3)
            rejected = message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)
        except aiohttp.WSServerHandshakeError:
            rejected = True
        assert rejected, "A neighbouring tab could read along the model stream"
    finally:
        await session.close()


async def test_websocket_vom_eigenen_frontend(backend):
    client = await BrowserClient(backend.url).connect(origin=BROWSER_ORIGIN)
    try:
        await wait_for(lambda: client.frames)
        assert client.frames[0]["type"] == "hello"
    finally:
        await client.close()


async def test_keine_cors_header(backend):
    async with backend.http.get(backend.url + "/api/status") as response:
        assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


# -- UI ---------------------------------------------------------------


async def test_spa_catch_all(backend):
    async with backend.http.get(backend.url + "/cad/anything") as response:
        assert response.status == 200
        assert "SysML-CAD Platform" in await response.text()


async def test_unbekannte_api_route_ist_json_404(backend):
    code, body = await backend.get("/api/doesnotexist")
    assert code == 404
    assert body["error"]["code"] == "not_found"


async def test_catch_all_liefert_keine_fremden_dateien(backend):
    for path in ("/..%2F..%2Fpyproject.toml", "/C:/Windows/win.ini", "/app/main.py"):
        async with backend.http.get(backend.url + path) as response:
            text = await response.text()
        assert "[project]" not in text and "create_app" not in text, path
