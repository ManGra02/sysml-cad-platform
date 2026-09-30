"""Entry point of the GUI phase.

DELIBERATELY MINIMAL. FreeCAD's loader reads this file and runs it via exec
INSIDE A FUNCTION. Two consequences that govern everything here:

  1. ``__file__`` is not defined  -> path via inspect.currentframe().
  2. Module-level names end up in that function's locals and are NOT
     visible from within methods (FreeCAD's own Mod/Assembly/InitGui.py
     carries a ``global`` workaround for this).

Hence only the bare minimum lives here; everything real lives in importable
modules.
"""

import inspect
import os
import sys

_addon_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

from bridge_addon.workbench import CadBridgeWorkbench  # noqa: E402

FreeCADGui.addWorkbench(CadBridgeWorkbench())  # noqa: F821  (injected by the loader)
