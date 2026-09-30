"""Bridge lifecycle: thread, asyncio loop, handshake, teardown.

The server runs in its own thread with its own asyncio loop. The loop handle
is stored in the state -- it is the only permitted channel from the Qt
thread into the asynchronous world (call_soon_threadsafe).

THE PORT IS FIXED. No automatic search: otherwise a second FreeCAD instance
overwrites the handshake file, the backend works on the wrong document, and
the Vite proxy points into nowhere. A port in use means a loud failure with
an understandable message.
"""

import asyncio
import threading

from freecad_bridge import auth, dispatch, events, log, observer, server, snapshot
from freecad_bridge import state as bridge_state

HOST = "127.0.0.1"
PORT = 8765

#: How often the snapshot is refreshed on the main thread.
HEARTBEAT_MS = 2000

_START_TIMEOUT_S = 10.0


_log = log.info
_warn = log.warn


def _serve_forever(state, generation, ready, failure):
    """Runs in the server thread: own loop, aiohttp, until stop() is set."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    state.loop = loop

    runner = None
    hub = None
    try:
        app = server.create_app()
        # The hub belongs to this thread's loop. Attach it before setup() --
        # after that the app state is frozen.
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

    # reuse_address deliberately off: a port in use should fail loudly.
    return web.TCPSite(runner, host, port, reuse_address=False)


def start_bridge():
    """Start the bridge. Defensively tears down an old instance."""
    state = bridge_state.get_state()

    if state.running:
        _log("already running on %s:%s" % (state.host, state.port))
        return state

    # Defensive: after a reload, the thread and observer of the old
    # generation may still be alive without running being set.
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
        state.last_error = "Server thread did not report in time"
        _warn(state.last_error)
        raise RuntimeError(state.last_error)

    if failure:
        exc = failure[0]
        if isinstance(exc, OSError):
            state.last_error = (
                "Port %s is in use. Is a second FreeCAD instance already running "
                "the bridge? Only one can serve at a time." % PORT
            )
        else:
            state.last_error = "Start failed: %s" % exc
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
        _warn("Snapshot at start failed: %s" % exc)

    _log("running on http://%s:%s  (session %s)" % (HOST, PORT, state.session_id[:8]))
    return state


def stop_bridge(quiet=False):
    """Idempotent, complete teardown.

    The order matters: first the flag, then resolve waiting tasks (instead
    of letting them run into the timeout), then stop the loop, then the
    handshake file -- and only if it belongs to our own session.
    """
    state = bridge_state.get_state()
    session_id = state.session_id
    was_running = state.running

    state.shutting_down = True

    # The observer first: otherwise it keeps reporting events during teardown
    # to a loop that is just being shut down.
    observer.uninstall(state)
    _stop_heartbeat(state)

    freed = dispatch.clear_queue()
    if freed and not quiet:
        _log("%d pending requests rejected" % freed)

    loop = state.loop
    stop_event = getattr(state, "stop_event", None)
    if loop is not None and stop_event is not None:
        try:
            loop.call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            pass  # loop already closed

    thread = state.thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=5.0)
        if thread.is_alive() and not quiet:
            _warn("Server thread does not respond; it is marked as daemon")

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
        _log("stopped")
    return state


# -- Heartbeat and FreeCAD shutdown -------------------------------------


def _install_heartbeat(state, generation):
    """QTimer on the main thread that keeps the snapshot fresh."""
    try:
        from PySide import QtCore
    except ImportError:
        return

    timer = QtCore.QTimer()
    timer.setInterval(HEARTBEAT_MS)

    def _tick():
        # Callbacks of an older generation terminate themselves.
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
    """Tear down cleanly when FreeCAD quits.

    FreeCAD itself uses the same pattern in
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
        log.debug("aboutToQuit hook: %s" % exc)
