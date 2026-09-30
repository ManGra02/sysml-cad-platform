"""The only legal way onto FreeCAD's main thread.

The FreeCAD API is not thread-safe: FreeCADApp.dll and FreeCADBase.dll
contain zero thread guards, and FreeCAD's own modules consistently marshal
with QTimer.singleShot(0, ...). Every access to documents, objects or views
therefore goes through this module.

TWO LEGAL HAND-OVERS, both via the asyncio loop held in the state:

  there   The handler creates an asyncio.Future, puts the task into the queue
          and waits with asyncio.wait_for(fut, ...). The Qt thread delivers
          back with loop.call_soon_threadsafe(fut.set_result, ...).
          NEVER a blocking queue.get() in a coroutine handler --
          aiohttp has ONE loop in ONE thread; a 20-second recompute
          would otherwise freeze the server, WS pushes and /health at once,
          and the backend would consider the bridge dead while FreeCAD is
          merely working.

  back    Observer events go via call_soon_threadsafe into an asyncio queue
          (see observer.py). The observer NEVER calls ws.send_str.

READING AND WRITING ARE DIFFERENT: reading changes nothing and always runs.
Writing is subject to the guard -- and a stricter one than the naive
"is a modal dialog open": sketcher edit and task dialogs are NOT
modal. A blocked write is rejected IMMEDIATELY, not
deferred: the UI can explain that, a 60-second timeout
cannot.
"""

import asyncio
import functools
import queue
import threading
import traceback

from freecad_bridge import log
from freecad_bridge import state as bridge_state

READ = "read"
WRITE = "write"

#: Upper bound of the write queue. Above it, 503 instead of unbounded growth.
MAX_WRITE_QUEUE = 50

_request_queue = queue.Queue()
_processing = False


class BridgeError(Exception):
    """Base for errors that go to the client as a structured response."""

    code = "bridge_error"
    http_status = 500

    def __init__(self, message, detail=None):
        super(BridgeError, self).__init__(message)
        self.message = message
        self.detail = detail


class CadBusyError(BridgeError):
    code = "cad_busy"
    http_status = 409


class QueueFullError(BridgeError):
    code = "queue_full"
    http_status = 503


class ShuttingDownError(BridgeError):
    code = "bridge_shutting_down"
    http_status = 503


class DispatchTimeout(BridgeError):
    code = "gui_busy"
    http_status = 504


class _Task(object):
    __slots__ = ("fn", "kind", "loop", "future", "cancel", "request_id")

    def __init__(self, fn, kind, loop, future, request_id):
        self.fn = fn
        self.kind = kind
        self.loop = loop
        self.future = future
        self.cancel = threading.Event()
        # No contextvar: it does not survive the thread switch. The ID is
        # a field on the task itself.
        self.request_id = request_id


# -- Main thread safeguard ---------------------------------------------


def on_main_thread():
    return threading.current_thread() is threading.main_thread()


def main_thread_only(fn):
    """Turns a non-deterministic hard crash into a clear error.

    Without this check, a forgotten dispatch() shows up as a crash
    somewhere in Coin3D, minutes later and without a usable stack trace.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not on_main_thread():
            raise RuntimeError(
                "%s was called from thread %r. Every FreeCAD access must go "
                "through dispatch() to the main thread."
                % (fn.__name__, threading.current_thread().name)
            )
        return fn(*args, **kwargs)

    return wrapper


# -- Guard --------------------------------------------------------------


def gui_block_reason():
    """Reason why writing is NOT allowed right now -- or None.

    Deliberately checks more than the naive modal guard: an open task dialog and
    an ongoing sketcher edit are not modal, but they are exactly the
    states in which a write destroys data.
    """
    try:
        import FreeCADGui
        from PySide import QtCore, QtWidgets
    except ImportError:
        return None  # headless: no GUI, nothing to protect

    app = QtWidgets.QApplication.instance()
    if app is None:
        return None

    if app.mouseButtons() != QtCore.Qt.NoButton:
        return "mouse_down"
    if app.activePopupWidget() is not None:
        return "popup_open"
    if app.activeModalWidget() is not None:
        return "modal_open"

    try:
        if FreeCADGui.Control.activeDialog():
            return "task_dialog"
    except Exception:
        pass

    try:
        active = getattr(FreeCADGui, "ActiveDocument", None)
        if active is not None and active.getInEdit() is not None:
            return "edit_mode"
    except Exception:
        pass

    return None


# -- Wake bridge (Qt signal, QueuedConnection) --------------------------


def _make_waker():
    """QObject whose signal triggers the drain on the main thread.

    Must be created on the main thread. Emitting from the server thread
    is safe: Qt delivers via QueuedConnection.
    """
    from PySide import QtCore

    class _Waker(QtCore.QObject):
        triggered = QtCore.Signal()

        def __init__(self):
            super(_Waker, self).__init__()
            self.triggered.connect(self._on_wake, QtCore.Qt.QueuedConnection)

        def wake(self):
            self.triggered.emit()

        def _on_wake(self):
            drain(reschedule=False)

    return _Waker()


# -- Drain (runs on the main thread) ------------------------------------


def drain(reschedule=True):
    """Process pending tasks. Exclusively on the main thread."""
    global _processing

    if _processing:
        return  # re-entrant via processEvents inside a task
    state = bridge_state.get_state()

    try:
        if _request_queue.empty():
            return
        _processing = True

        while not _request_queue.empty():
            task = _request_queue.get()
            if task.cancel.is_set():
                continue

            if task.kind == WRITE:
                reason = gui_block_reason()
                if reason is not None:
                    _resolve_exception(
                        task, CadBusyError("CAD is currently not writable", reason)
                    )
                    continue
            try:
                result = task.fn()
            except BridgeError as exc:
                _resolve_exception(task, exc)
            except Exception as exc:
                log.error(
                    "Task raised %s: %s\n%s"
                    % (type(exc).__name__, exc, traceback.format_exc()),
                    task.request_id,
                )
                _resolve_exception(task, exc)
            else:
                _resolve_result(task, result)
    finally:
        _processing = False
        if reschedule and not state.shutting_down:
            try:
                from PySide import QtCore

                QtCore.QTimer.singleShot(500, drain)
            except ImportError:
                pass


def _resolve_result(task, value):
    if task.future.cancelled():
        return
    task.loop.call_soon_threadsafe(_set_if_pending, task.future, value, None)


def _resolve_exception(task, exc):
    if task.future.cancelled():
        return
    task.loop.call_soon_threadsafe(_set_if_pending, task.future, None, exc)


def _set_if_pending(future, value, exc):
    if future.done():
        return
    if exc is not None:
        future.set_exception(exc)
    else:
        future.set_result(value)


# -- Public API ---------------------------------------------------------


async def dispatch(fn, kind=READ, timeout=30.0, request_id=None):
    """Run fn on FreeCAD's main thread and return the result.

    Fast path: if everything already runs on the main thread (headless, tests),
    it is called directly. Without this every test would run into the timeout,
    because without a QApplication there is nobody to drain the queue.
    """
    state = bridge_state.get_state()
    if state.shutting_down:
        raise ShuttingDownError("The bridge is shutting down")

    if fast_path_available():
        if kind == WRITE:
            reason = gui_block_reason()
            if reason is not None:
                raise CadBusyError("CAD is currently not writable", reason)
        return fn()

    if kind == WRITE and _request_queue.qsize() >= MAX_WRITE_QUEUE:
        raise QueueFullError("Too many pending writes")

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    task = _Task(fn, kind, loop, future, request_id)
    _request_queue.put(task)

    waker = getattr(state, "waker", None)
    if waker is not None:
        waker.wake()

    try:
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        # The wait is over -- the task must not run later after all.
        task.cancel.set()
        raise DispatchTimeout(
            "FreeCAD did not respond within %ss" % timeout
        )


def fast_path_available():
    """Only a caller that is already ON the main thread may run directly.

    Previously "no QApplication -> direct" applied as well. That was wrong:
    if the real server runs headless (tests), the server thread then executed
    FreeCAD code. @main_thread_only caught exactly that. Without a GUI,
    somebody therefore has to call drain() on the main thread -- in GUI mode
    the Qt signal and heartbeat do that, in tests a small pump.
    """
    return on_main_thread()


def install_waker(state):
    """Create the wake bridge. Call only from the main thread."""
    try:
        from PySide import QtCore

        if QtCore.QCoreApplication.instance() is None:
            state.waker = None  # headless: nobody delivers signals
        else:
            state.waker = _make_waker()
    except ImportError:
        state.waker = None
    return state.waker


def clear_queue(reason="Bridge is shutting down"):
    """Resolve all pending tasks instead of letting them run into the timeout."""
    drained = 0
    while not _request_queue.empty():
        try:
            task = _request_queue.get_nowait()
        except queue.Empty:
            break
        task.cancel.set()
        _resolve_exception(task, ShuttingDownError(reason))
        drained += 1
    return drained


def queue_depth():
    return _request_queue.qsize()
