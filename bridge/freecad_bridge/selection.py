"""Read and set the selection -- the bridge between the two windows.

A click in FreeCAD shows the object in the browser; a click in the browser
brings it into view in the 3D view. That costs two routes and turns two
side-by-side windows into one coherent tool.

Everything here is GUI-bound. Headless, FreeCADGui is a stub without
getDocument, and obj.ViewObject is None -- so every function falls back
cleanly to "no GUI" instead of raising.

Sub-element names (Face1, Edge2) are transported and displayed, but NEVER
used as a persisted identity: topological naming makes them unstable between
two recomputes. The mapping granularity is the object.
"""

from freecad_bridge.dispatch import BridgeError, main_thread_only


class NoGuiError(BridgeError):
    code = "no_gui"
    http_status = 409


def _gui():
    try:
        import FreeCADGui

        if not hasattr(FreeCADGui, "Selection"):
            return None
        return FreeCADGui
    except ImportError:
        return None


@main_thread_only
def get_selection():
    """What is currently selected in FreeCAD."""
    gui = _gui()
    if gui is None:
        return {"available": False, "selection": []}

    entries = []
    try:
        for selection in gui.Selection.getSelectionEx():
            obj = selection.Object
            entries.append(
                {
                    "doc": obj.Document.Name,
                    "name": obj.Name,
                    "label": obj.Label,
                    "typeId": obj.TypeId,
                    "subs": list(selection.SubElementNames or []),
                }
            )
    except Exception as exc:
        return {"available": False, "selection": [], "error": type(exc).__name__}

    return {"available": True, "selection": entries}


@main_thread_only
def set_selection(refs, zoom_to_fit=True):
    """Select in the 3D view and optionally bring into view.

    ``refs`` is a list of {doc, name, subs?}.
    """
    gui = _gui()
    if gui is None:
        raise NoGuiError("No FreeCAD GUI -- selection not available")

    gui.Selection.clearSelection()

    applied, missing = [], []
    for ref in refs or []:
        doc_name = ref.get("doc")
        obj_name = ref.get("name")
        subs = ref.get("subs") or [None]
        try:
            for sub in subs:
                if sub:
                    gui.Selection.addSelection(doc_name, obj_name, sub)
                else:
                    gui.Selection.addSelection(doc_name, obj_name)
            applied.append({"doc": doc_name, "name": obj_name})
        except Exception:
            missing.append({"doc": doc_name, "name": obj_name})

    zoomed = False
    if zoom_to_fit and applied:
        zoomed = _fit_selection(gui)

    result = {"selected": applied, "zoomed": zoomed}
    if missing:
        result["missing"] = missing
    return result


def _fit_selection(gui):
    """Zoom the view to the selection.

    setActiveDocument is needed if the target is not the active document --
    otherwise the wrong view zooms.
    """
    try:
        view = gui.ActiveDocument.ActiveView
    except Exception:
        return False
    for method in ("fitSelection", "fitAll"):
        action = getattr(view, method, None)
        if action is None:
            continue
        try:
            action()
            return True
        except Exception:
            continue
    return False
