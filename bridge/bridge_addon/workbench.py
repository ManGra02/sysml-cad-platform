"""Die Workbench der CAD-Bruecke.

Der Klassenname ``CadBridgeWorkbench`` muss exakt dem <classname> in
package.xml entsprechen -- FreeCAD registriert die Workbench unter ihrem
Python-Klassennamen und holt sie ueber ``Gui.getWorkbench(classname)``, um das
Icon zu setzen.
"""

import os

import FreeCAD
import FreeCADGui


def _qt_translate_noop(_context, text):
    return text


class CadBridgeWorkbench(FreeCADGui.Workbench):
    """Stellt Start/Stop der Bruecke und das Status-Panel bereit."""

    def __init__(self):
        addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.__class__.Icon = os.path.join(addon_dir, "Resources", "icons", "bridge.svg")
        self.__class__.MenuText = _qt_translate_noop("SysMLCadBridge", "SysML-CAD Bruecke")
        self.__class__.ToolTip = _qt_translate_noop(
            "SysMLCadBridge",
            "Stellt das CAD-Modell fuer die SysML-CAD-Plattform bereit (nur lokal)",
        )

    def Initialize(self):
        """Wird beim ERSTEN Aktivieren aufgerufen, nicht beim Start."""
        from bridge_addon import commands  # noqa: F401  (registriert via addCommand)

        command_names = commands.register_all()
        self.appendToolbar(_qt_translate_noop("Workbench", "SysML-CAD Bruecke"), command_names)
        self.appendMenu(_qt_translate_noop("Workbench", "SysML-CAD Bruecke"), command_names)

    def Activated(self):
        """Beim Betreten der Workbench das Status-Panel zeigen."""
        try:
            from bridge_addon import dock_panel

            dock_panel.show_panel()
        except Exception as exc:  # nie die Workbench am Panel scheitern lassen
            FreeCAD.Console.PrintError("[Bruecke] Dock-Panel konnte nicht geoeffnet werden: %s\n" % exc)

    def Deactivated(self):
        """Panel bleibt bestehen -- FreeCAD stellt Docks ueber den ObjectName wieder her."""
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"
