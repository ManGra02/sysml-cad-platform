"""Der einzige legale Weg auf FreeCADs Hauptthread.

Die FreeCAD-API ist nicht threadsicher: FreeCADApp.dll und FreeCADBase.dll
enthalten null Thread-Guards, und FreeCADs eigene Module marshallen konsequent
mit QTimer.singleShot(0, ...). Jeder Zugriff auf Dokument, Objekte oder Views
laeuft deshalb durch dieses Modul.

ZWEI LEGALE UEBERGAENGE, beide ueber den im State gehaltenen asyncio-Loop:

  hin     Der Handler erzeugt ein asyncio.Future, legt die Task in die Queue
          und wartet mit asyncio.wait_for(fut, ...). Der Qt-Thread liefert mit
          loop.call_soon_threadsafe(fut.set_result, ...) zurueck.
          NIEMALS ein blockierendes queue.get() in einem Coroutine-Handler --
          aiohttp hat EINEN Loop in EINEM Thread; ein 20-Sekunden-Recompute
          wuerde sonst Server, WS-Pushes und /health gleichzeitig einfrieren,
          und das Backend hielte die Bruecke fuer tot, waehrend FreeCAD nur
          arbeitet.

  zurueck Observer-Events gehen per call_soon_threadsafe in eine asyncio-Queue
          (siehe observer.py). Der Observer ruft NIE ws.send_str.

LESEN UND SCHREIBEN SIND VERSCHIEDEN: Lesen veraendert nichts und laeuft immer.
Schreiben unterliegt dem Guard -- und zwar einem schaerferen als dem naiven
"ist ein modaler Dialog offen": Sketcher-Edit und Task-Dialoge sind NICHT
modal. Ein blockierter Schreibzugriff wird SOFORT abgewiesen, nicht
aufgeschoben: das kann die Oberflaeche erklaeren, ein 60-Sekunden-Timeout
nicht.
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

#: Obergrenze der Schreib-Warteschlange. Darueber 503 statt unbegrenztem Wachstum.
MAX_WRITE_QUEUE = 50

_request_queue = queue.Queue()
_processing = False


class BridgeError(Exception):
    """Basis fuer Fehler, die als strukturierte Antwort zum Client gehen."""

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
        # Kein contextvar: das ueberlebt den Thread-Wechsel nicht. Die ID ist
        # ein Feld an der Task selbst.
        self.request_id = request_id


# -- Hauptthread-Absicherung -------------------------------------------


def on_main_thread():
    return threading.current_thread() is threading.main_thread()


def main_thread_only(fn):
    """Macht aus einem nicht-deterministischen Hardcrash einen klaren Fehler.

    Ohne diese Pruefung aeussert sich ein vergessener dispatch() als Absturz
    irgendwo in Coin3D, Minuten spaeter und ohne verwertbaren Stacktrace.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not on_main_thread():
            raise RuntimeError(
                "%s wurde aus Thread %r aufgerufen. Jeder FreeCAD-Zugriff muss "
                "ueber dispatch() auf den Hauptthread."
                % (fn.__name__, threading.current_thread().name)
            )
        return fn(*args, **kwargs)

    return wrapper


# -- Guard --------------------------------------------------------------


def gui_block_reason():
    """Grund, warum gerade NICHT geschrieben werden darf -- oder None.

    Prueft bewusst mehr als der naive Modal-Guard: ein offener Task-Dialog und
    eine laufende Sketcher-Bearbeitung sind nicht modal, sind aber genau die
    Zustaende, in denen ein Schreibzugriff Daten zerstoert.
    """
    try:
        import FreeCADGui
        from PySide import QtCore, QtWidgets
    except ImportError:
        return None  # headless: kein GUI, nichts zu schuetzen

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


# -- Wake-Bruecke (Qt-Signal, QueuedConnection) -------------------------


def _make_waker():
    """QObject, dessen Signal den Drain auf dem Hauptthread ausloest.

    Muss auf dem Hauptthread erzeugt werden. Emittieren aus dem Server-Thread
    ist sicher: Qt stellt ueber QueuedConnection zu.
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


# -- Drain (laeuft auf dem Hauptthread) ---------------------------------


def drain(reschedule=True):
    """Wartende Tasks abarbeiten. Ausschliesslich auf dem Hauptthread."""
    global _processing

    if _processing:
        return  # re-entrant durch processEvents innerhalb einer Task
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
                        task, CadBusyError("CAD ist gerade nicht beschreibbar", reason)
                    )
                    continue
            try:
                result = task.fn()
            except BridgeError as exc:
                _resolve_exception(task, exc)
            except Exception as exc:
                log.error(
                    "Task warf %s: %s\n%s"
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


# -- Oeffentliche API ---------------------------------------------------


async def dispatch(fn, kind=READ, timeout=30.0, request_id=None):
    """fn auf FreeCADs Hauptthread ausfuehren und das Ergebnis liefern.

    Fast-Path: laeuft bereits alles auf dem Hauptthread (headless, Tests), wird
    direkt aufgerufen. Ohne das liefe jeder Test in den Timeout, weil es ohne
    QApplication niemanden gibt, der die Queue leert.
    """
    state = bridge_state.get_state()
    if state.shutting_down:
        raise ShuttingDownError("Die Bruecke wird gerade beendet")

    if fast_path_available():
        if kind == WRITE:
            reason = gui_block_reason()
            if reason is not None:
                raise CadBusyError("CAD ist gerade nicht beschreibbar", reason)
        return fn()

    if kind == WRITE and _request_queue.qsize() >= MAX_WRITE_QUEUE:
        raise QueueFullError("Zu viele wartende Schreibvorgaenge")

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
        # Das Warten ist beendet -- die Task darf nicht spaeter doch noch laufen.
        task.cancel.set()
        raise DispatchTimeout(
            "FreeCAD hat nicht innerhalb von %ss geantwortet" % timeout
        )


def fast_path_available():
    """Direkt ausfuehren darf nur, wer bereits AUF dem Hauptthread ist.

    Frueher galt zusaetzlich "kein QApplication -> direkt". Das war falsch:
    laeuft der echte Server headless (Tests), fuehrte der Server-Thread dann
    FreeCAD-Code aus. @main_thread_only hat genau das gefangen. Ohne GUI muss
    deshalb jemand auf dem Hauptthread drain() aufrufen -- im GUI-Betrieb tun
    das Qt-Signal und Heartbeat, in Tests eine kleine Pumpe.
    """
    return on_main_thread()


def install_waker(state):
    """Wake-Bruecke anlegen. Nur vom Hauptthread aufrufen."""
    try:
        from PySide import QtCore

        if QtCore.QCoreApplication.instance() is None:
            state.waker = None  # headless: niemand stellt Signale zu
        else:
            state.waker = _make_waker()
    except ImportError:
        state.waker = None
    return state.waker


def clear_queue(reason="Bruecke wird beendet"):
    """Alle wartenden Tasks aufloesen, statt sie in den Timeout laufen zu lassen."""
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
