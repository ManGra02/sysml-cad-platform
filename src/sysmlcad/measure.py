"""Messkern: CAD-Property -> einheitenbehaftete Groesse.

Jede Messmethode hat eine dokumentierte Semantik. "Laenge" ist nicht
selbsterklaerend -- Bounding-Box-Ausdehnung und benanntes Feature-Mass
sind verschiedene Dinge, und die Verwechslung faellt erst bei der
ersten Schraege auf.
"""

from __future__ import annotations

from importlib import import_module
from typing import Callable

from build123d import Part

from .units import Q, ureg


def bbox_size(part: Part, axis: str = "X") -> Q:
    """Ausdehnung der achsparallelen Huellbox entlang der Modellachse."""
    size = part.bounding_box().size
    return getattr(size, axis.upper()) * ureg.mm


def volume(part: Part) -> Q:
    """Solid-Volumen aus dem B-Rep."""
    return part.volume * ureg.mm**3


def mass(part: Part, density_g_per_cm3: float) -> Q:
    """Volumen mal Dichte. Homogenes Material vorausgesetzt."""
    rho = density_g_per_cm3 * ureg.g / ureg.cm**3
    return (volume(part) * rho).to(ureg.kg)


def face_count(part: Part) -> Q:
    """Topologische Kennzahl -- fuer Regressionstests der Geometrie."""
    return len(part.faces()) * ureg.dimensionless


METHODS: dict[str, Callable[..., Q]] = {
    "bbox_size": bbox_size,
    "volume": volume,
    "mass": mass,
    "face_count": face_count,
}


def load_part(module_name: str) -> tuple[Part, object]:
    """Laedt ein CAD-Skript und ruft dessen build() auf."""
    mod = import_module(module_name)
    return mod.build(), mod


def measure(part: Part, method: str, args: dict | None = None) -> Q:
    if method not in METHODS:
        raise KeyError(f"Unbekannte Messmethode: {method}")
    return METHODS[method](part, **(args or {}))
