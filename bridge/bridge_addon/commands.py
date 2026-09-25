"""FreeCAD-Befehle der Bruecke.

GetResources() darf nur Strings enthalten (ausser Checkable/Exclusive/
DropDownMenu) -- FreeCAD prueft das und meldet sonst
"returns a dictionary which holds not only strings".
"""

import webbrowser

import FreeCAD
import FreeCADGui

from freecad_bridge import runner
from freecad_bridge import state as bridge_state

#: Wohin "Oberflaeche oeffnen" zeigt. Das Backend liefert die SPA aus.
BACKEND_URL = "http://127.0.0.1:8000/"


def _report(exc, what):
    FreeCAD.Console.PrintError("[Bruecke] %s fehlgeschlagen: %s\n" % (what, exc))


def _refresh_panel():
    try:
        from bridge_addon import dock_panel

        dock_panel.refresh_panel()
    except Exception:
        pass


class StartBridgeCommand(object):
    def GetResources(self):
        return {
            "Pixmap": "bridge",
            "MenuText": "Bruecke starten",
            "ToolTip": "Startet den lokalen Dienst, ueber den die Plattform auf das CAD-Modell zugreift",
        }

    def IsActive(self):
        return not bridge_state.get_state().running

    def Activated(self):
        try:
            runner.start_bridge()
        except Exception as exc:
            _report(exc, "Start der Bruecke")
        _refresh_panel()


class StopBridgeCommand(object):
    def GetResources(self):
        return {
            "Pixmap": "bridge",
            "MenuText": "Bruecke stoppen",
            "ToolTip": "Beendet den lokalen Dienst und raeumt Observer, Thread und Handshake-Datei ab",
        }

    def IsActive(self):
        return bridge_state.get_state().running

    def Activated(self):
        try:
            runner.stop_bridge()
        except Exception as exc:
            _report(exc, "Stoppen der Bruecke")
        _refresh_panel()


class OpenUiCommand(object):
    def GetResources(self):
        return {
            "Pixmap": "bridge",
            "MenuText": "Oberflaeche oeffnen",
            "ToolTip": "Oeffnet die Plattform-Oberflaeche im Standardbrowser",
        }

    def IsActive(self):
        return True

    def Activated(self):
        try:
            webbrowser.open(BACKEND_URL)
        except Exception as exc:
            _report(exc, "Oeffnen des Browsers")


class ShowPanelCommand(object):
    def GetResources(self):
        return {
            "Pixmap": "bridge",
            "MenuText": "Status-Panel zeigen",
            "ToolTip": "Blendet das Status-Panel der Bruecke wieder ein",
        }

    def IsActive(self):
        return True

    def Activated(self):
        try:
            from bridge_addon import dock_panel

            dock_panel.show_panel()
        except Exception as exc:
            _report(exc, "Anzeigen des Panels")


_COMMANDS = (
    ("SysMLCadBridge_Start", StartBridgeCommand),
    ("SysMLCadBridge_Stop", StopBridgeCommand),
    ("SysMLCadBridge_OpenUI", OpenUiCommand),
    ("SysMLCadBridge_ShowPanel", ShowPanelCommand),
)


def register_all():
    """Alle Befehle registrieren und ihre Namen fuer Toolbar/Menue liefern."""
    names = []
    for name, cls in _COMMANDS:
        FreeCADGui.addCommand(name, cls())
        names.append(name)
    return names
