"""FreeCAD commands of the bridge.

GetResources() may contain only strings (except Checkable/Exclusive/
DropDownMenu) -- FreeCAD checks this and otherwise reports
"returns a dictionary which holds not only strings".
"""

import webbrowser

import FreeCAD
import FreeCADGui

from bridge_addon.i18n import tr
from freecad_bridge import runner
from freecad_bridge import state as bridge_state

#: Where "Open user interface" points. The backend serves the SPA.
BACKEND_URL = "http://127.0.0.1:8000/"


def _report(exc, what):
    FreeCAD.Console.PrintError("[Bridge] %s\n" % tr("failed", what=what, error=exc))


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
            "MenuText": tr("cmd.start"),
            "ToolTip": tr("cmd.start.tip"),
        }

    def IsActive(self):
        return not bridge_state.get_state().running

    def Activated(self):
        try:
            runner.start_bridge()
        except Exception as exc:
            _report(exc, tr("fail.start"))
        _refresh_panel()


class StopBridgeCommand(object):
    def GetResources(self):
        return {
            "Pixmap": "bridge",
            "MenuText": tr("cmd.stop"),
            "ToolTip": tr("cmd.stop.tip"),
        }

    def IsActive(self):
        return bridge_state.get_state().running

    def Activated(self):
        try:
            runner.stop_bridge()
        except Exception as exc:
            _report(exc, tr("fail.stop"))
        _refresh_panel()


class OpenUiCommand(object):
    def GetResources(self):
        return {
            "Pixmap": "bridge",
            "MenuText": tr("cmd.open"),
            "ToolTip": tr("cmd.open.tip"),
        }

    def IsActive(self):
        return True

    def Activated(self):
        try:
            webbrowser.open(BACKEND_URL)
        except Exception as exc:
            _report(exc, tr("fail.browser"))


class ShowPanelCommand(object):
    def GetResources(self):
        return {
            "Pixmap": "bridge",
            "MenuText": tr("cmd.panel"),
            "ToolTip": tr("cmd.panel.tip"),
        }

    def IsActive(self):
        return True

    def Activated(self):
        try:
            from bridge_addon import dock_panel

            dock_panel.show_panel()
        except Exception as exc:
            _report(exc, tr("fail.panel"))


_COMMANDS = (
    ("SysMLCadBridge_Start", StartBridgeCommand),
    ("SysMLCadBridge_Stop", StopBridgeCommand),
    ("SysMLCadBridge_OpenUI", OpenUiCommand),
    ("SysMLCadBridge_ShowPanel", ShowPanelCommand),
)


def register_all():
    """Register all commands and return their names for toolbar/menu."""
    names = []
    for name, cls in _COMMANDS:
        FreeCADGui.addCommand(name, cls())
        names.append(name)
    return names
