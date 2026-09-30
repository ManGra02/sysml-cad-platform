"""Read documents.

Identity is always ``doc.Name`` -- immutable and unique. ``Label`` is
only displayed. ``doc.Uid`` is explicitly NOT a key: two copies of the
same file share it (verified). For persisted state the normalized
absolute ``FileName`` is the right key; if it is empty, the document was
never saved and cannot be referenced.
"""

import os

import FreeCAD

from freecad_bridge.dispatch import BridgeError, main_thread_only


class DocumentNotOpen(BridgeError):
    code = "doc_not_open"
    http_status = 404


@main_thread_only
def get_document(name):
    """Get the document or respond with an error the UI understands.

    Important for the frontend: on doc.closed it should navigate, not run into
    a retry loop -- hence a dedicated code instead of a generic 404.
    """
    try:
        doc = FreeCAD.getDocument(name)
    except Exception:
        doc = None
    if doc is None:
        raise DocumentNotOpen("Document %r is not open" % name, name)
    return doc


@main_thread_only
def gui_document(name):
    """GUI document if a GUI is running -- otherwise None."""
    try:
        import FreeCADGui

        return FreeCADGui.getDocument(name)
    except Exception:
        return None


@main_thread_only
def is_modified(name):
    """The dirty state lives on the GUI document.

    Verified: doc.Modified does NOT exist on the App document.
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
    """UndoMode = 0 makes transactions ineffective -- without any error.

    The bridge does not open documents, the user does. That is why this is
    re-applied here at every opportunity instead of once at startup.
    """
    try:
        if doc.UndoMode == 0:
            doc.UndoMode = 1
            return True
    except Exception:
        pass
    return False
