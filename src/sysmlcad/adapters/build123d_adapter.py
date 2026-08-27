"""CAD side backed by build123d scripts under `cad/`.

This is code-CAD: there is no document, no assembly tree and no material
database. One "object" is one importable module exposing `build() -> Part`,
and its named module-level constants are its parameters. That is a real
limitation, not a modelling choice -- `material()` returns whatever the script
declares and None otherwise, and the caller reports the gap.

Kept as the reference implementation because it needs no external
application, which is what lets CI verify geometry offline.
"""

from __future__ import annotations

import hashlib
import inspect
from importlib import import_module
from types import ModuleType

from build123d import Part

from ..units import Q, ureg
from . import Material, Unsupported

#: Suffix conventions in the CAD scripts, so a parameter comes back with units
#: instead of as a bare float. Explicit table rather than guesswork.
_SUFFIX_UNITS = {
    "_MM": ureg.mm,
    "_DEG": ureg.degree,
    "_G_PER_CM3": ureg.g / ureg.cm**3,
    "_KG": ureg.kg,
}


class Build123dAdapter:
    """Addresses build123d scripts by module name."""

    name = "build123d"

    def __init__(self, objects: list[str] | None = None):
        self._declared = list(objects or [])
        self._modules: dict[str, ModuleType] = {}
        self._parts: dict[str, Part] = {}

    # -- loading ------------------------------------------------------------

    def _module(self, obj: str) -> ModuleType:
        if obj not in self._modules:
            try:
                self._modules[obj] = import_module(obj)
            except ImportError as exc:
                raise Unsupported(f"no CAD module named {obj!r}: {exc}") from exc
            if obj not in self._declared:
                self._declared.append(obj)
        return self._modules[obj]

    def _part(self, obj: str) -> Part:
        """Build once per run. Geometry is expensive and does not change mid-run."""
        if obj not in self._parts:
            module = self._module(obj)
            if not hasattr(module, "build"):
                raise Unsupported(f"CAD module {obj!r} has no build()")
            self._parts[obj] = module.build()
        return self._parts[obj]

    # -- CadAdapter ---------------------------------------------------------

    def state_id(self) -> str:
        """Digest of the source of every module loaded so far.

        For code-CAD the script *is* the design state, so hashing the source is
        exact rather than approximate.
        """
        digest = hashlib.sha256()
        for obj in sorted(self._declared):
            try:
                source = inspect.getsource(self._module(obj))
            except (OSError, TypeError, Unsupported):
                source = ""
            digest.update(obj.encode())
            digest.update(source.encode())
        return digest.hexdigest()[:16]

    def objects(self) -> list[str]:
        return list(self._declared)

    def parameter(self, obj: str, name: str) -> Q | None:
        module = self._module(obj)
        if not hasattr(module, name):
            return None
        value = getattr(module, name)
        if isinstance(value, Q):
            return value
        if not isinstance(value, (int, float)):
            return None
        for suffix, unit in _SUFFIX_UNITS.items():
            if name.endswith(suffix):
                return value * unit
        return value * ureg.dimensionless

    def material(self, obj: str) -> Material | None:
        """Read what the script declares. No default, no substitution."""
        module = self._module(obj)
        density = self.parameter(obj, "DENSITY_G_PER_CM3")
        name = getattr(module, "MATERIAL", None)
        if name is None and density is None:
            return None
        return Material(name=name or "unnamed", density=density)

    def measure(self, obj: str, method: str, args: dict | None = None) -> Q:
        if method not in _METHODS:
            raise Unsupported(f"unknown measurement method: {method}")
        return _METHODS[method](self, obj, **(args or {}))

    # -- measurement vocabulary ---------------------------------------------

    def _bbox_size(self, obj: str, axis: str = "X") -> Q:
        size = self._part(obj).bounding_box().size
        return getattr(size, axis.upper()) * ureg.mm

    def _volume(self, obj: str) -> Q:
        return self._part(obj).volume * ureg.mm**3

    def _mass(self, obj: str, density_g_per_cm3: float | None = None) -> Q:
        """Volume times density, homogeneous material assumed.

        Density comes from the object's material. The override exists for
        replacement-part studies ("what if this were plastic?"), which is
        exactly the SRS's substitution case -- so it stays, but it is no longer
        the only way to get a density, and the CAD script is the default source
        of truth for its own material.
        """
        if density_g_per_cm3 is not None:
            rho = density_g_per_cm3 * ureg.g / ureg.cm**3
        else:
            material = self.material(obj)
            if material is None or material.density is None:
                raise Unsupported(
                    f"{obj} has no material and no density override -- "
                    f"cannot compute mass"
                )
            rho = material.density
        return (self._volume(obj) * rho).to(ureg.kg)

    def _face_count(self, obj: str) -> Q:
        return len(self._part(obj).faces()) * ureg.dimensionless


_METHODS = {
    "bbox_size": Build123dAdapter._bbox_size,
    "volume": Build123dAdapter._volume,
    "mass": Build123dAdapter._mass,
    "face_count": Build123dAdapter._face_count,
}
