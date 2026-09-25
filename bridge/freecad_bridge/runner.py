"""Lebenszyklus der Bruecke: Thread, asyncio-Loop, Handshake, Abbau.

Der Server laeuft in einem eigenen Thread mit eigenem asyncio-Loop. Der
Loop-Handle wird im State abgelegt -- er ist die einzige erlaubte Ruecksprache
vom Qt-Thread in die asynchrone Welt (call_soon_threadsafe).

PORT IST FEST. Keine automatische Suche: sonst ueberschreibt eine zweite
FreeCAD-Instanz die Handshake-Datei, das Backend arbeitet am falschen Dokument,
und der Vite-Proxy zeigt ins Leere. Belegter Port heisst lauter Fehlschlag mit
verstaendlicher Meldung.
"""

import asyncio
import threading

from freecad_bridge import auth, dispatch, events, log, observer, server, snapshot
from freecad_bridge import state as bridge_state

HOST = "127.0.0.1"
PORT = 8765

#: Wie oft der Snapshot auf dem Hauptthread aufgefrischt wird.
HEARTBEAT_MS = 2000

_START_TIMEOUT_S = 10.0


_log = log.info
_warn = log.warn


def _serve_forever(state, generation, ready, failure):
    """Laeuft im Server-Thread: eigener Loop, aiohttp, bis stop() gesetzt wird."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    state.loop = loop

    runner = None
    hub = None
    try:
        app = server.create_app()
        # Der Hub gehoert dem Loop dieses Threads. Vor setup() anhaengen --
        # danach ist der App-Zustand eingefroren.
        hub = events.EventHub(loop, state.session_id)
        app["websockets"] = hub.clients
        app["hub"] = hub
        state.hub = hub
        runner = web_runner(app)
        loop.run_until_complete(runner.setup())
        site = tcp_site(runner, HOST, PORT)
        loop.run_until_complete(site.start())

        state.runner = runner
        state.stop_event = asyncio.Event()
        hub.start()
        ready.set()

        loop.run_until_complete(state.stop_event.wait())
    except Exception as exc:
        failure.append(exc)
        ready.set()
    finally:
        try:
            if hub is not None:
                loop.run_until_complete(hub.close())
        except Exception:
            pass
        try:
            if runner is not None:
                loop.run_until_complete(runner.cleanup())
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass
        if state.generation == generation:
            state.loop = None
            state.runner = None


def web_runner(app):
    from aiohttp import web

    return web.AppRunner(app)


def tcp_site(runner, host, port):
    from aiohttp import web

    # reuse_address bewusst aus: ein belegter Port soll laut scheitern.
    return web.TCPSite(runner, host, port, reuse_address=False)


def start_bridge():
    """Bruecke starten. Raeumt defensiv eine alte Instanz ab."""
    state = bridge_state.get_state()

    if state.running:
        _log("laeuft bereits auf %s:%s" % (state.host, state.port))
        return state

    # Defensiv: nach einem Reload koennen Thread und Observer der alten
    # Generation noch leben, ohne dass running gesetzt ist.
    stop_bridge(quiet=True)

    generation = state.begin_session()
    state.host = HOST
    state.port = PORT
    state.token = auth.new_token()

    dispatch.install_waker(state)

    ready = threading.Event()
    failure = []
    thread = threading.Thread(
        target=_serve_forever,
        args=(state, generation, ready, failure),
        name="sysml-cad-bridge",
        daemon=True,
    )
    state.thread = thread
    thread.start()

    if not ready.wait(_START_TIMEOUT_S):
        state.last_error = "Server-Thread hat nicht rechtzeitig gemeldet"
        _warn(state.last_error)
        raise RuntimeError(state.last_error)

    if failure:
        exc = failure[0]
        if isinstance(exc, OSError):
            state.last_error = (
                "Port %s ist belegt. Laeuft bereits eine zweite FreeCAD-Instanz "
                "mit der Bruecke? Es bedient immer nur eine." % PORT
            )
        else:
            state.last_error = "Start fehlgeschlagen: %s" % exc
        _warn(state.last_error)
        state.thread = None
        raise RuntimeError(state.last_error)

    hub = state.hub
    observer.install(state, publish=hub.publish_threadsafe)

    auth.write_handshake(PORT, state.token, state.session_id)
    state.running = True
    state.last_error = None

    _install_heartbeat(state, generation)
    _install_quit_hook(state)

    try:
        snapshot.refresh()
    except Exception as exc:
        _warn("Snapshot beim Start fehlgeschlagen: %s" % exc)

    _log("laeuft auf http://%s:%s  (Sitzung %s)" % (HOST, PORT, state.session_id[:8]))
    return state


def stop_bridge(quiet=False):
    """Idempotenter, vollstaendiger Abbau.

    Wichtig ist die Reihenfolge: erst das Flag, dann wartende Tasks aufloesen
    (statt sie in den Timeout laufen zu lassen), dann den Loop beenden, dann
    die Handshake-Datei -- und die nur, wenn sie zur eigenen Sitzung gehoert.
    """
    state = bridge_state.get_state()
    session_id = state.session_id
    was_running = state.running

    state.shutting_down = True

    # Zuerst den Observer: sonst meldet er waehrend des Abbaus noch Ereignisse
    # an einen Loop, der gerade beendet wird.
    observer.uninstall(state)
    _stop_heartbeat(state)

    freed = dispatch.clear_queue()
    if freed and not quiet:
        _log("%d wartende Anfragen abgewiesen" % freed)

    loop = state.loop
    stop_event = getattr(state, "stop_event", None)
    if loop is not None and stop_event is not None:
        try:
            loop.call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            pass  # Loop bereits geschlossen

    thread = state.thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=5.0)
        if thread.is_alive() and not quiet:
            _warn("Server-Thread reagiert nicht; er ist als daemon markiert")

    if session_id:
        auth.remove_handshake(session_id)

    state.thread = None
    state.loop = None
    state.runner = None
    state.stop_event = None
    state.hub = None
    state.waker = None
    state.running = False
    state.shutting_down = False

    if was_running and not quiet:
        _log("gestoppt")
    return state


# -- Heartbeat und Beenden von FreeCAD ----------------------------------


def _install_heartbeat(state, generation):
    """QTimer auf dem Hauptthread, der den Snapshot frisch haelt."""
    try:
        from PySide import QtCore
    except ImportError:
        return

    timer = QtCore.QTimer()
    timer.setInterval(HEARTBEAT_MS)

    def _tick():
        # Callbacks einer aelteren Generation beenden sich selbst.
        if state.generation != generation or not state.running:
            timer.stop()
            return
        try:
            snapshot.refresh()
        except Exception as exc:
            log.debug("Heartbeat: %s" % exc)

    timer.timeout.connect(_tick)
    timer.start()
    state.flush_timer = timer


def _stop_heartbeat(state):
    timer = state.flush_timer
    if timer is None:
        return
    try:
        timer.stop()
        timer.timeout.disconnect()
    except Exception:
        pass
    state.flush_timer = None


def _install_quit_hook(state):
    """Beim Beenden von FreeCAD sauber abbauen.

    Dasselbe Muster benutzt FreeCAD selbst in
    Mod/AddonManager/NetworkManager.py.
    """
    if getattr(state, "quit_hook_installed", False):
        return
    try:
        from PySide import QtCore

        app = QtCore.QCoreApplication.instance()
        if app is None:
            return
        app.aboutToQuit.connect(lambda: stop_bridge(quiet=True))
        state.quit_hook_installed = True
    except Exception as exc:
        log.debug("aboutToQuit-Hook: %s" % exc)
