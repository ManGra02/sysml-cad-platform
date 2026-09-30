"""The workbench of the CAD bridge.

The class name ``CadBridgeWorkbench`` must exactly match the <classname> in
package.xml -- FreeCAD registers the workbench under its Python class name
and retrieves it via ``Gui.getWorkbench(classname)`` in order to set the
icon.
"""

import os

import FreeCAD
import FreeCADGui


def _tr(key):
    # Import only here: InitGui loads this module before FreeCAD is fully up.
    from bridge_addon.i18n import tr

    return tr(key)


class CadBridgeWorkbench(FreeCADGui.Workbench):
    """Provides start/stop of the bridge and the status panel."""

    def __init__(self):
        addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.__class__.Icon = os.path.join(addon_dir, "Resources", "icons", "bridge.svg")
        self.__class__.MenuText = _tr("workbench.menu")
        self.__class__.ToolTip = _tr("workbench.tooltip")

    def Initialize(self):
        """Called on the FIRST activation, not at startup."""
        from bridge_addon import commands  # noqa: F401  (registers via addCommand)

        command_names = commands.register_all()
        self.appendToolbar(_tr("workbench.menu"), command_names)
        self.appendMenu(_tr("workbench.menu"), command_names)

    def Activated(self):
        """Show the status panel when entering the workbench."""
        try:
            from bridge_addon import dock_panel

            dock_panel.show_panel()
        except Exception as exc:  # never let the workbench fail because of the panel
            FreeCAD.Console.PrintError("[Bridge] Could not open the dock panel: %s\n" % exc)

    def Deactivated(self):
        """Panel stays -- FreeCAD restores docks via their ObjectName."""
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"
