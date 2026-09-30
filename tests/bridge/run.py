"""Entry point for the bridge tests.

Usage:
    PYTHONNOUSERSITE=1 "<FreeCAD>/bin/python.exe" tests/bridge/run.py

WHY NOT ``freecadcmd -t``: it prints "FAILED (errors=1)" and still returns
exit code 0. A CI built on that would be permanently green. Here the exit
code is derived explicitly from the result.

WHY NOT pytest: pytest is not installed in FreeCAD's Python, and nothing gets
installed into FreeCAD's Python. aiohttp.test_utils and stdlib unittest are
entirely sufficient.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_BRIDGE = os.path.join(_REPO, "bridge")

for path in (_BRIDGE, _HERE):
    if path not in sys.path:
        sys.path.insert(0, path)


def main():
    try:
        import FreeCAD
    except ImportError:
        sys.stderr.write(
            "FreeCAD cannot be imported.\n"
            "These tests must run with FreeCAD's bundled Python:\n"
            '  "<FreeCAD>/bin/python.exe" tests/bridge/run.py\n'
        )
        return 2

    sys.stdout.write(
        "FreeCAD %s | GuiUp=%s | Python %s\n\n"
        % (".".join(FreeCAD.Version()[:3]), FreeCAD.GuiUp, sys.version.split()[0])
    )

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=_HERE, pattern="test_*.py", top_level_dir=_HERE)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
