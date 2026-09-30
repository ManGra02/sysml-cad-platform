"""The state snapshot that /api/cad/health reads.

WHY A SNAPSHOT AT ALL: If /health dispatched, the liveness check would lie
precisely when FreeCAD is working hardest -- a 20-second recompute holds
the main thread, /health would run into the timeout, the backend would mark
"not connected" and tear down the WS connection. Of all times, while
everything is fine.

Instead, heartbeat and observer update the snapshot ON the main thread;
the handler only reads and always answers immediately.
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
    """The dirty state lives on the GUI document, not the App document.

    Verified: doc.Modified does NOT exist on the App document.
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
    """Collect the snapshot anew. Main thread only."""
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
    """Read the snapshot. Allowed from any thread -- a plain copy."""
    with _lock:
        return copy.deepcopy(_snapshot)


def note_event(seq):
    """Called by the observer so last_seq keeps up without a full refresh."""
    with _lock:
        _snapshot["last_seq"] = seq
