"""Der Zustands-Schnappschuss, den /api/cad/health liest.

WARUM UEBERHAUPT EIN SNAPSHOT: Wuerde /health dispatchen, luege der
Liveness-Check genau dann, wenn FreeCAD am meisten arbeitet -- ein
20-Sekunden-Recompute haelt den Hauptthread, /health liefe in den Timeout,
das Backend markierte "nicht verbunden" und baute die WS-Verbindung ab.
Ausgerechnet waehrend alles in Ordnung ist.

Stattdessen aktualisieren Heartbeat und Observer den Snapshot AUF dem
Hauptthread; der Handler liest nur und antwortet immer sofort.
"""

import copy
import threading

import FreeCAD

from cad_contract.version import CONTRACT_VERSION
from freecad_bridge import state as bridge_state
from freecad_bridge.dispatch import main_thread_only

_lock = threading.Lock()
_snapshot = {
    "freecad_version": None,
    "contract_version": CONTRACT_VERSION,
    "session_id": None,
    "pid": None,
    "active_document": None,
    "documents": [],
    "modified": {},
    "busy": False,
    "queue_depth": 0,
    "last_seq": 0,
}


def _gui_modified_flag(doc_name):
    """Dirty-Zustand haengt am GUI-Dokument, nicht am App-Dokument.

    Verifiziert: doc.Modified existiert auf dem App-Dokument NICHT.
    """
    try:
        import FreeCADGui

        gui_doc = FreeCADGui.getDocument(doc_name)
    except Exception:
        return None
    try:
        return bool(gui_doc.Modified)
    except Exception:
        return None


@main_thread_only
def refresh():
    """Snapshot neu erheben. Nur auf dem Hauptthread."""
    from freecad_bridge import dispatch

    state = bridge_state.get_state()

    try:
        documents = list(FreeCAD.listDocuments())
    except Exception:
        documents = []

    active = None
    try:
        active_doc = FreeCAD.activeDocument()
        if active_doc is not None:
            active = active_doc.Name
    except Exception:
        pass

    modified = {}
    for name in documents:
        flag = _gui_modified_flag(name)
        if flag is not None:
            modified[name] = flag

    data = {
        "freecad_version": ".".join(FreeCAD.Version()[:3]),
        "contract_version": CONTRACT_VERSION,
        "session_id": state.session_id,
        "pid": _pid(),
        "active_document": active,
        "documents": documents,
        "modified": modified,
        "busy": dispatch.queue_depth() > 0,
        "queue_depth": dispatch.queue_depth(),
        "last_seq": state.event_seq,
    }

    with _lock:
        _snapshot.update(data)
    return data


def _pid():
    import os

    return os.getpid()


def read():
    """Snapshot lesen. Von jedem Thread aus erlaubt -- reine Kopie."""
    with _lock:
        return copy.deepcopy(_snapshot)


def note_event(seq):
    """Vom Observer aufgerufen, damit last_seq ohne vollen Refresh mitlaeuft."""
    with _lock:
        _snapshot["last_seq"] = seq
