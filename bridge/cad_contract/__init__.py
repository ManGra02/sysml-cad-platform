"""Shared, dependency-free contract between bridge and backend.

This package physically lives in the addon directory so FreeCAD can import it
without sys.path code and without a .pth (``import FreeCAD`` puts all
user Mod subdirectories on the path itself). The backend includes the same
directory as an editable install.

HARD RULE: no dependencies outside the standard library, and
nothing FreeCAD's Python 3.11 does not understand (no PEP 695).
"""

from cad_contract.version import CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION"]
