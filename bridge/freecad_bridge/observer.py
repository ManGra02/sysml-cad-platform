"""Aenderungen in FreeCAD erkennen und als Ereignisse melden.

MENGENPROBLEM: Das Oeffnen von BIMExample.FCStd (361 Objekte) erzeugt 26.971
Observer-Callbacks, ein einzelner Property-Change 7. Alles synchron auf dem
Hauptthread. Deshalb gilt:

  * Ein Slot ist O(1). Er traegt (doc, obj, prop) in ein Dict ein -- keine
    Serialisierung, kein Wertzugriff, kein Kontakt zum asyncio-Loop.
  * Geflusht wird KOALESZIERT, nicht entprellt: an den Grenzen, die FreeCAD
    selbst liefert (Commit, Abbruch, Undo, Redo, Recompute), plus ein QTimer
    mit ~100 ms Maximallatenz fuer Aenderungen ausserhalb jeder Transaktion.
    Ein reiner Zeit-Debouncer wuerde mitten in einem Undo flushen: die
    Aenderungen kommen VOR slotUndoDocument (empirisch geprueft).
  * Restore-Klammer: solange doc.Restoring/Importing gesetzt ist, werden
    Objektereignisse verworfen. Danach geht EIN doc.opened hinaus. Der
    App-Observer hat kein slotFinishRestoreDocument -- das Flag ist der Ersatz.
  * Ereignisse tragen nur IDENTITAET, keine Werte. Der Browser liest ueber die
    normale Route nach, die einen konsistenten Stand sieht.

Jeder Slot laeuft in try/except: eine Exception wuerde in FreeCADs C++-Signal
propagieren.

Nach slotDeletedObject feuern noch Aenderungen am geloeschten Objekt
(AttachmentSupport) -- die werden verworfen.
"""

import collections
import functools

import FreeCAD

from freecad_bridge import documents, log, revisions, snapshot
from freecad_bridge import state as bridge_state

#: Maximale Verzoegerung fuer Aenderungen ausserhalb einer Transaktion.
FLUSH_LATENCY_MS = 100

USER_ORIGIN = "freecad:user"


def _safe(fn):
    """Kein Fehler darf in FreeCADs Signal-Kette gelangen."""

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
        self._opening = set()        # Dokumente, deren Restore noch laeuft
        self._last_modified = {}     # doc -> letzter gemeldeter Dirty-Zustand
        self._timer = None

    def _reset_pending(self):
        self._changed = collections.OrderedDict()   # (doc, obj) -> set(props)
        self._created = collections.OrderedDict()   # (doc, obj) -> True
        self._deleted = collections.OrderedDict()
        self._schema = collections.OrderedDict()
        self._labels = {}
        self._origins = {}                            # (doc, obj) -> set(origin)
        self._doc_events = []

    # -- Aufzeichnen (O(1)) ---------------------------------------------

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
            return  # interne Buchhaltung (_ElementMapVersion ...)
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

    # Die Metadaten, aus denen der Editor rendert, sind nicht statisch:
    # slotChangePropertyEditor aendert ReadOnly/Hidden OHNE Wertaenderung.
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

    # -- Dokumentereignisse ---------------------------------------------

    def _doc_event(self, event_type, doc, **extra):
        event = {"type": event_type, "doc": doc.Name}
        event.update(extra)
        self._doc_events.append(event)
        self._schedule()

    @_safe
    def slotCreatedDocument(self, doc):
        # Neu oder geladen: in jedem Fall erst melden, wenn der Restore vorbei ist.
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

    # -- Flush-Grenzen, die FreeCAD selbst liefert ----------------------

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
        # Undo eines Create feuert slotDeletedObject, Undo eines Delete feuert
        # slotCreatedObject -- die Slots sagen nicht, dass es ein Undo war.
        # Das Backend verwirft bei cad.history den Cache des Dokuments.
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
        """QTimer fuer Aenderungen ausserhalb jeder Transaktion.

        Headless gibt es keine Ereignisschleife -- dort ruft der Test flush().
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
        """Dokumente, deren Restore vorbei ist, als geoeffnet melden."""
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
            # Nachzuegler-Aenderungen direkt nach dem Restore gehen im
            # vollstaendigen Neuladen auf, das doc.opened ohnehin ausloest.
            self._drop_doc(doc_name)
            documents.ensure_undo_enabled(doc)
            events.append({"type": "doc.opened", "doc": doc_name,
                           "label": doc.Label, "objectCount": len(doc.Objects)})

    def _modified_events(self, doc_names, events):
        """Dirty-Wechsel melden (nur mit GUI verfuegbar)."""
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
        """Gesammelte Aenderungen als ein Batch melden. Nur auf dem Hauptthread."""
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
            log.debug("Publish fehlgeschlagen: %r" % (exc,))
        return events


# -- Installation --------------------------------------------------------


def install(state, publish):
    """Observer registrieren. Idempotent; entfernt einen alten zuerst."""
    uninstall(state)
    observer = BridgeObserver(publish)
    FreeCAD.addDocumentObserver(observer)
    state.observer = observer

    # UndoMode fuer alle bereits offenen Dokumente nachziehen -- die Bruecke
    # oeffnet keine Dokumente, der Nutzer tut es.
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
    """Sofort flushen -- von writes.py nach einem Commit aufgerufen."""
    observer = getattr(bridge_state.get_state(), "observer", None)
    if observer is None:
        return []
    return observer.flush(cause)
