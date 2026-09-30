"""Detect changes in FreeCAD and report them as events.

VOLUME PROBLEM: Opening BIMExample.FCStd (361 objects) produces 26,971
observer callbacks, a single property change 7. All synchronous on the
main thread. Therefore:

  * A slot is O(1). It records (doc, obj, prop) in a dict -- no
    serialization, no value access, no contact with the asyncio loop.
  * Flushing is COALESCED, not debounced: at the boundaries FreeCAD itself
    provides (commit, abort, undo, redo, recompute), plus a QTimer
    with ~100 ms maximum latency for changes outside any transaction.
    A pure time-based debouncer would flush in the middle of an undo: the
    changes arrive BEFORE slotUndoDocument (verified empirically).
  * Restore bracket: while doc.Restoring/Importing is set, object events
    are discarded. Afterwards ONE doc.opened goes out. The
    App observer has no slotFinishRestoreDocument -- the flag is the substitute.
  * Events carry only IDENTITY, no values. The browser re-reads via the
    normal route, which sees a consistent state.

Every slot runs in try/except: an exception would propagate into FreeCAD's
C++ signal.

After slotDeletedObject, changes to the deleted object still fire
(AttachmentSupport) -- those are discarded.
"""

import collections
import functools

import FreeCAD

from freecad_bridge import documents, log, revisions, snapshot
from freecad_bridge import state as bridge_state

#: Maximum delay for changes outside a transaction.
FLUSH_LATENCY_MS = 100

USER_ORIGIN = "freecad:user"


def _safe(fn):
    """No error may reach FreeCAD's signal chain."""

    @functools.wraps(fn)
    def wrapper(self, *args):
        try:
            return fn(self, *args)
        except Exception as exc:
            log.debug("Observer %s: %r" % (fn.__name__, exc))
            return None

    return wrapper


def _busy_restoring(doc):
    return bool(getattr(doc, "Restoring", False) or getattr(doc, "Importing", False))


class BridgeObserver(object):
    def __init__(self, publish):
        self._publish = publish
        self._reset_pending()
        self._opening = set()        # documents whose restore is still running
        self._last_modified = {}     # doc -> last reported dirty state
        self._timer = None

    def _reset_pending(self):
        self._changed = collections.OrderedDict()   # (doc, obj) -> set(props)
        self._created = collections.OrderedDict()   # (doc, obj) -> True
        self._deleted = collections.OrderedDict()
        self._schema = collections.OrderedDict()
        self._labels = {}
        self._origins = {}                            # (doc, obj) -> set(origin)
        self._doc_events = []

    # -- Recording (O(1)) -----------------------------------------------

    def _origin(self):
        request_id = getattr(bridge_state.get_state(), "active_request_id", None)
        return "bridge:%s" % request_id if request_id else USER_ORIGIN

    def _key(self, obj):
        doc = obj.Document
        if doc is None or _busy_restoring(doc):
            if doc is not None:
                self._opening.add(doc.Name)
            return None
        return (doc.Name, obj.Name)

    def _note(self, key, obj):
        self._labels[key] = getattr(obj, "Label", None)
        self._origins.setdefault(key, set()).add(self._origin())
        self._schedule()

    @_safe
    def slotCreatedObject(self, obj):
        key = self._key(obj)
        if key is None:
            return
        self._created[key] = True
        self._note(key, obj)

    @_safe
    def slotDeletedObject(self, obj):
        key = self._key(obj)
        if key is None:
            return
        self._deleted[key] = True
        self._note(key, obj)

    @_safe
    def slotChangedObject(self, obj, prop):
        if prop.startswith("_"):
            return  # internal bookkeeping (_ElementMapVersion ...)
        key = self._key(obj)
        if key is None:
            return
        self._changed.setdefault(key, set()).add(prop)
        self._note(key, obj)

    def _schema_changed(self, obj):
        key = self._key(obj)
        if key is None:
            return
        self._schema[key] = True
        self._note(key, obj)

    # The metadata the editor renders from is not static:
    # slotChangePropertyEditor changes ReadOnly/Hidden WITHOUT a value change.
    @_safe
    def slotAppendDynamicProperty(self, obj, prop):
        self._schema_changed(obj)

    @_safe
    def slotRemoveDynamicProperty(self, obj, prop):
        self._schema_changed(obj)

    @_safe
    def slotChangePropertyEditor(self, obj, prop):
        self._schema_changed(obj)

    @_safe
    def slotAddedDynamicExtension(self, obj, ext):
        self._schema_changed(obj)

    # -- Document events ------------------------------------------------

    def _doc_event(self, event_type, doc, **extra):
        event = {"type": event_type, "doc": doc.Name}
        event.update(extra)
        self._doc_events.append(event)
        self._schedule()

    @_safe
    def slotCreatedDocument(self, doc):
        # New or loaded: in either case report only once the restore is over.
        self._opening.add(doc.Name)
        self._schedule()

    @_safe
    def slotDeletedDocument(self, doc):
        name = doc.Name
        self._opening.discard(name)
        self._last_modified.pop(name, None)
        self._drop_doc(name)
        self._doc_events.append({"type": "doc.closed", "doc": name})
        self.flush("close")

    @_safe
    def slotRelabelDocument(self, doc):
        if _busy_restoring(doc) or doc.Name in self._opening:
            return
        self._doc_event("doc.relabeled", doc, label=doc.Label)

    @_safe
    def slotActivateDocument(self, doc):
        if _busy_restoring(doc):
            return
        self._doc_event("doc.activated", doc)

    @_safe
    def slotFinishSaveDocument(self, doc, file_name):
        self._doc_event("doc.saved", doc, fileName=file_name, label=doc.Label)

    # -- Flush boundaries provided by FreeCAD itself -------------------

    @_safe
    def slotCommitTransaction(self, doc):
        name = doc.UndoNames[0] if getattr(doc, "UndoNames", None) else None
        self._doc_events.append({"type": "cad.transaction", "doc": doc.Name,
                                 "result": "committed", "name": name})
        self.flush("commit")

    @_safe
    def slotAbortTransaction(self, doc):
        self._doc_events.append({"type": "cad.transaction", "doc": doc.Name,
                                 "result": "aborted"})
        self.flush("abort")

    @_safe
    def slotUndoDocument(self, doc):
        # Undo of a create fires slotDeletedObject, undo of a delete fires
        # slotCreatedObject -- the slots do not say that it was an undo.
        # On cad.history the backend discards the document's cache.
        self._doc_events.append({"type": "cad.history", "doc": doc.Name, "action": "undo"})
        self.flush("undo")

    @_safe
    def slotRedoDocument(self, doc):
        self._doc_events.append({"type": "cad.history", "doc": doc.Name, "action": "redo"})
        self.flush("redo")

    @_safe
    def slotRecomputedDocument(self, doc):
        if _busy_restoring(doc):
            return
        self._doc_events.append({"type": "cad.recomputed", "doc": doc.Name})
        self.flush("recompute")

    # -- Flush -----------------------------------------------------------

    def _drop_doc(self, doc_name):
        for table in (self._changed, self._created, self._deleted, self._schema):
            for key in [k for k in table if k[0] == doc_name]:
                del table[key]

    def _schedule(self):
        """QTimer for changes outside any transaction.

        Headless there is no event loop -- there the test calls flush().
        """
        if self._timer is not None:
            return
        try:
            from PySide import QtCore
        except ImportError:
            return
        if QtCore.QCoreApplication.instance() is None:
            return
        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.setInterval(FLUSH_LATENCY_MS)
        timer.timeout.connect(lambda: self.flush("timer"))
        timer.start()
        self._timer = timer

    def _finish_openings(self, events):
        """Report documents whose restore is over as opened."""
        for doc_name in list(self._opening):
            try:
                doc = FreeCAD.getDocument(doc_name)
            except Exception:
                doc = None
            if doc is None:
                self._opening.discard(doc_name)
                continue
            if _busy_restoring(doc):
                continue
            self._opening.discard(doc_name)
            # Straggler changes right after the restore are subsumed by the
            # full reload that doc.opened triggers anyway.
            self._drop_doc(doc_name)
            documents.ensure_undo_enabled(doc)
            events.append({"type": "doc.opened", "doc": doc_name,
                           "label": doc.Label, "objectCount": len(doc.Objects)})

    def _modified_events(self, doc_names, events):
        """Report dirty-state changes (available only with a GUI)."""
        for doc_name in doc_names:
            dirty = documents.is_modified(doc_name) if FreeCAD.GuiUp else None
            if dirty is None:
                continue
            if self._last_modified.get(doc_name) != dirty:
                self._last_modified[doc_name] = dirty
                events.append({"type": "doc.modified", "doc": doc_name, "dirty": dirty})

    def _object_event(self, event_type, key, cause):
        doc_name, obj_name = key
        origins = self._origins.get(key, {USER_ORIGIN})
        origin = next(iter(origins)) if len(origins) == 1 else "mixed"
        return {
            "type": event_type,
            "doc": doc_name,
            "obj": obj_name,
            "label": self._labels.get(key),
            "origin": origin,
            "cause": cause,
        }

    def flush(self, cause="timer"):
        """Report collected changes as one batch. Main thread only."""
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None

        events = []
        self._finish_openings(events)
        events.extend(self._doc_events)

        touched_docs = {e["doc"] for e in events if "doc" in e}

        for key in self._deleted:
            events.append(self._object_event("cad.deleted", key, cause))
        for key in self._created:
            if key in self._deleted:
                continue
            event = self._object_event("cad.created", key, cause)
            event["rev"] = revisions.bump(*key)
            events.append(event)
        for key, props in self._changed.items():
            if key in self._deleted or key in self._created:
                continue
            event = self._object_event("cad.changed", key, cause)
            event["props"] = sorted(props)
            event["rev"] = revisions.bump(*key)
            events.append(event)
        for key in self._schema:
            if key in self._deleted:
                continue
            events.append(self._object_event("cad.schema_changed", key, cause))

        for key in list(self._deleted) + list(self._created) + list(self._changed):
            touched_docs.add(key[0])

        self._reset_pending()
        self._modified_events(sorted(touched_docs), events)

        if not events:
            return []

        state = bridge_state.get_state()
        for event in events:
            event["seq"] = state.next_seq()
            event["session_id"] = state.session_id
            doc_name = event.get("doc")
            if doc_name and "transacting" not in event:
                try:
                    event["transacting"] = bool(FreeCAD.getDocument(doc_name).Transacting)
                except Exception:
                    event["transacting"] = False

        snapshot.note_event(state.event_seq)
        try:
            self._publish(events)
        except Exception as exc:
            log.debug("Publish failed: %r" % (exc,))
        return events


# -- Installation --------------------------------------------------------


def install(state, publish):
    """Register the observer. Idempotent; removes an old one first."""
    uninstall(state)
    observer = BridgeObserver(publish)
    FreeCAD.addDocumentObserver(observer)
    state.observer = observer

    # Apply UndoMode to all already open documents -- the bridge does not
    # open documents, the user does.
    for name in FreeCAD.listDocuments():
        try:
            documents.ensure_undo_enabled(FreeCAD.getDocument(name))
        except Exception:
            pass
    return observer


def uninstall(state):
    observer = getattr(state, "observer", None)
    if observer is None:
        return
    try:
        FreeCAD.removeDocumentObserver(observer)
    except Exception:
        pass
    if observer._timer is not None:
        try:
            observer._timer.stop()
        except Exception:
            pass
    state.observer = None


def flush_now(cause="write"):
    """Flush immediately -- called by writes.py after a commit."""
    observer = getattr(bridge_state.get_state(), "observer", None)
    if observer is None:
        return []
    return observer.flush(cause)
