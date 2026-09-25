"""Dokumente lesen.

Identitaet ist immer ``doc.Name`` -- unveraenderlich und eindeutig. ``Label``
wird nur angezeigt. ``doc.Uid`` ist ausdruecklich KEIN Schluessel: zwei Kopien
derselben Datei teilen sie (verifiziert). Fuer persistierten Zustand ist der
normalisierte absolute ``FileName`` der richtige Schluessel; ist er leer, wurde
das Dokument nie gespeichert und ist nicht referenzierbar.
"""

import os

import FreeCAD

from freecad_bridge.dispatch import BridgeError, main_thread_only


class DocumentNotOpen(BridgeError):
    code = "doc_not_open"
    http_status = 404


@main_thread_only
def get_document(name):
    """Dokument holen oder mit einem Fehler antworten, den die UI versteht.

    Wichtig fuer das Frontend: bei doc.closed soll es navigieren, nicht in eine
    Retry-Schleife laufen -- deshalb ein eigener Code statt eines generischen 404.
    """
    try:
        doc = FreeCAD.getDocument(name)
    except Exception:
        doc = None
    if doc is None:
        raise DocumentNotOpen("Dokument %r ist nicht geoeffnet" % name, name)
    return doc


@main_thread_only
def gui_document(name):
    """GUI-Dokument, falls eine Oberflaeche laeuft -- sonst None."""
    try:
        import FreeCADGui

        return FreeCADGui.getDocument(name)
    except Exception:
        return None


@main_thread_only
def is_modified(name):
    """Dirty-Zustand haengt am GUI-Dokument.

    Verifiziert: doc.Modified existiert auf dem App-Dokument NICHT.
    """
    gui_doc = gui_document(name)
    if gui_doc is None:
        return None
    try:
        return bool(gui_doc.Modified)
    except Exception:
        return None


@main_thread_only
def describe_document(doc):
    file_name = doc.FileName or ""
    return {
        "name": doc.Name,
        "label": doc.Label,
        "fileName": os.path.normpath(file_name) if file_name else None,
        "saved": bool(file_name),
        "modified": is_modified(doc.Name),
        "objectCount": len(doc.Objects),
        "undoCount": getattr(doc, "UndoCount", None),
        "undoNames": list(getattr(doc, "UndoNames", []) or []),
        "transacting": bool(getattr(doc, "Transacting", False)),
        "restoring": bool(getattr(doc, "Restoring", False)),
    }


@main_thread_only
def list_documents():
    active = FreeCAD.activeDocument()
    active_name = active.Name if active is not None else None

    documents = []
    for name in FreeCAD.listDocuments():
        try:
            documents.append(describe_document(FreeCAD.getDocument(name)))
        except Exception:
            continue
    return {"documents": documents, "active": active_name}


@main_thread_only
def ensure_undo_enabled(doc):
    """UndoMode = 0 macht Transaktionen wirkungslos -- ohne jeden Fehler.

    Die Bruecke oeffnet keine Dokumente, der Nutzer tut es. Deshalb wird das
    hier bei jeder Gelegenheit nachgezogen statt einmalig beim Start.
    """
    try:
        if doc.UndoMode == 0:
            doc.UndoMode = 1
            return True
    except Exception:
        pass
    return False
