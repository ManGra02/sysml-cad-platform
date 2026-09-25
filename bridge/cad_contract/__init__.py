"""Gemeinsamer, abhaengigkeitsfreier Vertrag zwischen Bruecke und Backend.

Dieses Paket liegt physisch im Addon-Verzeichnis, damit FreeCAD es ohne
sys.path-Code und ohne .pth importieren kann (``import FreeCAD`` legt alle
User-Mod-Unterverzeichnisse selbst auf den Pfad). Das Backend bindet dasselbe
Verzeichnis editierbar ein.

HARTE REGEL: keine Abhaengigkeiten ausserhalb der Standardbibliothek, und
nichts, was FreeCADs Python 3.11 nicht versteht (kein PEP-695).
"""

from cad_contract.version import CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION"]
