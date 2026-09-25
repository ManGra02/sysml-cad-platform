"""Auswahl lesen und setzen -- die Bruecke zwischen beiden Fenstern.

Klick in FreeCAD zeigt das Objekt im Browser; Klick im Browser faehrt es in der
3D-Ansicht an. Das kostet zwei Routen und macht aus zwei nebeneinander-
stehenden Fenstern ein zusammenhaengendes Werkzeug.

Alles hier ist GUI-gebunden. Headless ist FreeCADGui ein Stub ohne
getDocument, und obj.ViewObject ist None -- deshalb faellt jede Funktion
sauber auf "keine Oberflaeche" zurueck, statt zu werfen.

Sub-Element-Namen (Face1, Edge2) werden transportiert und angezeigt, aber NIE
als persistierte Identitaet verwendet: topologisches Naming macht sie zwischen
zwei Recomputes instabil. Mapping-Granularitaet ist das Objekt.
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
    """Was gerade in FreeCAD ausgewaehlt ist."""
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
    """Im 3D-Fenster auswaehlen und optional anfahren.

    ``refs`` ist eine Liste von {doc, name, subs?}.
    """
    gui = _gui()
    if gui is None:
        raise NoGuiError("Keine FreeCAD-Oberflaeche -- Auswahl nicht moeglich")

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
    """Ansicht auf die Auswahl zoomen.

    setActiveDocument ist noetig, wenn das Ziel nicht das aktive Dokument ist --
    sonst zoomt die falsche Ansicht.
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
