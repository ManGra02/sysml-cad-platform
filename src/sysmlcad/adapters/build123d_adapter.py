"""CAD side backed by build123d scripts under `cad/`.

This is code-CAD: there is no document and no material database. One "object"
is one importable module exposing `build() -> Part`, and its named module-level
constants are its parameters. `material()` returns whatever the script declares
and None otherwise, and the caller reports the gap.

ADDRESSING
----------
    motor_housing            the module's build()
    gearbox#Housing          the module's build_housing()

The `#` form mirrors the STEP adapter's, and it exists to fix a real hole. An
assembly script's `build()` returns the whole assembly, so without it a
component could only be measured through the STEP export -- which carries no
material, which meant a density had to be written into `mapping.yaml`. That put
a *fact about the part* into the file that is supposed to hold only the
*correspondence between the two models*, and made the mapping a third source of
truth that neither model owns. Changing the script's material then left the
mapping silently stale: the check would keep using the old density and report a
confident, wrong mass.

With `#`, a component is addressable in the script that declares its material,
and the density comes from there. See `test_a_component_inherits_the_script_material`.

Kept as the reference implementation because it needs no external application,
which is what lets CI verify geometry offline.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from importlib import import_module
from pathlib import Path
from types import ModuleType

from build123d import Part

from ..units import Q, ureg
from . import METHODS, CadTarget, Material, Unsupported, check_args, check_density
from . import measurements as mm

#: Where the CAD scripts live, for `catalog()`. The modules are addressed by
#: import name; this path only answers "which names exist".
CAD_DIR = Path(__file__).resolve().parents[3] / "cad"

#: A component is built by `build_<snake_case(name)>`. One convention, spelled
#: out, so a mapping entry can be read without opening the script.
BUILDER_PREFIX = "build_"


def _snake(name: str) -> str:
    """`Housing` -> `housing`, `GearRing` -> `gear_ring`."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^0-9a-zA-Z]+", "_", spaced).strip("_").lower()


#: Suffix conventions in the CAD scripts, so a parameter comes back with units
#: instead of as a bare float. Explicit table rather than guesswork.
_SUFFIX_UNITS = {
    "_MM": ureg.mm,
    "_DEG": ureg.degree,
    "_G_PER_CM3": ureg.g / ureg.cm**3,
    "_KG": ureg.kg,
}


class Build123dAdapter:
    """Addresses build123d scripts by module name, optionally `module#Component`."""

    name = "build123d"

    def __init__(self, objects: list[str] | None = None):
        self._declared = list(objects or [])
        self._modules: dict[str, ModuleType] = {}
        self._parts: dict[str, Part] = {}

    # -- addressing ---------------------------------------------------------

    @staticmethod
    def _resolve(obj: str) -> tuple[str, str | None]:
        """`gearbox#Housing` -> `("gearbox", "Housing")`."""
        module_name, _, component = obj.partition("#")
        return module_name, (component or None)

    # -- loading ------------------------------------------------------------

    def _module(self, obj: str) -> ModuleType:
        module_name, _ = self._resolve(obj)
        if module_name not in self._modules:
            try:
                self._modules[module_name] = import_module(module_name)
            except ImportError as exc:
                raise Unsupported(f"no CAD module named {module_name!r}: {exc}") from exc
        if obj not in self._declared:
            self._declared.append(obj)
        return self._modules[module_name]

    def _builders(self, module: ModuleType) -> dict[str, str]:
        """Component name -> builder function name, for one module."""
        return {
            attr[len(BUILDER_PREFIX):].title().replace("_", ""): attr
            for attr in dir(module)
            if attr.startswith(BUILDER_PREFIX) and callable(getattr(module, attr, None))
        }

    def _part(self, obj: str) -> Part:
        """Build once per run. Geometry is expensive and does not change mid-run."""
        if obj in self._parts:
            return self._parts[obj]

        module_name, component = self._resolve(obj)
        module = self._module(obj)

        if component is None:
            if not hasattr(module, "build"):
                raise Unsupported(f"CAD module {module_name!r} has no build()")
            self._parts[obj] = module.build()
            return self._parts[obj]

        builder = getattr(module, BUILDER_PREFIX + _snake(component), None)
        if not callable(builder):
            available = ", ".join(sorted(self._builders(module))) or "none"
            raise Unsupported(
                f"{module_name} has no component {component!r} "
                f"(expected a {BUILDER_PREFIX}{_snake(component)}() function). "
                f"Available: {available}"
            )
        self._parts[obj] = builder()
        return self._parts[obj]

    # -- CadAdapter ---------------------------------------------------------

    def state_id(self) -> str:
        """Digest of the source of every module loaded so far.

        For code-CAD the script *is* the design state, so hashing the source is
        exact rather than approximate.
        """
        digest = hashlib.sha256()
        # By module, not by reference: two components of one script share a
        # design state, and hashing the source twice would say otherwise.
        modules = sorted({self._resolve(obj)[0] for obj in self._declared})
        for module_name in modules:
            try:
                source = inspect.getsource(self._module(module_name))
            except (OSError, TypeError, Unsupported):
                source = ""
            digest.update(module_name.encode())
            digest.update(source.encode())
        return digest.hexdigest()[:16]

    def objects(self) -> list[str]:
        return list(self._declared)

    def parameter(self, obj: str, name: str) -> Q | None:
        """Module-level, so every component of a script shares its parameters --
        which is correct: `DENSITY_G_PER_CM3` describes the material the whole
        script is made of."""
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
        args = dict(args or {})
        check_args(method, _METHODS[method], self, obj, **args)
        return _METHODS[method](self, obj, **args)

    def catalog(self, objects: list[str] | None = None) -> list[CadTarget]:
        """One target per CAD script, with its named parameters.

        Named parameters are what this backend has and a STEP file does not, so
        they are the interesting half of its catalogue: `LENGTH_MM` is a
        candidate for a length attribute in a way a bounding box never quite is.
        """
        names = objects if objects is not None else self._known_modules()
        out: list[CadTarget] = []

        for name in names:
            try:
                module = self._module(name)
            except Unsupported:
                continue
            if not hasattr(module, "build"):
                continue

            parameters = {}
            for attr in dir(module):
                if attr.startswith("_") or not attr.isupper():
                    continue
                value = self.parameter(name, attr)
                if value is not None:
                    parameters[attr] = value

            # `mass` needs a density. Offering it without one would propose a
            # mapping whose only possible outcome is a gap.
            material = self.material(name)
            methods = tuple(
                m for m in METHODS
                if m != "mass" or (material is not None and material.density is not None)
            )
            note = f"material {material.name}" if material else "no material declared"
            out.append(CadTarget(
                adapter=self.name,
                reference=name,
                kind="module",
                name=name,
                methods=methods,
                parameters=parameters,
                note=note,
            ))

            # Components, where the script builds them separately. They share
            # the module's material, which is the whole point: a component
            # addressed here needs no density written into the mapping.
            for component in sorted(self._builders(module)):
                out.append(CadTarget(
                    adapter=self.name,
                    reference=f"{name}#{component}",
                    kind="part",
                    name=component,
                    methods=methods,
                    parameters=parameters,
                    note=f"{note}, component of {name}",
                ))
        return out

    def _known_modules(self) -> list[str]:
        """Declared modules first, then whatever `cad/` offers."""
        found = list(self._declared)
        if CAD_DIR.is_dir():
            for path in sorted(CAD_DIR.glob("*.py")):
                if not path.name.startswith("_") and path.stem not in found:
                    found.append(path.stem)
        return found

    # -- measurement vocabulary ---------------------------------------------

    def _bbox_size(self, obj: str, axis: str = "X") -> Q:
        key = str(axis).upper()
        if key not in ("X", "Y", "Z"):
            raise Unsupported(f"bbox_size: axis must be X, Y or Z, not {axis!r}")
        size = self._part(obj).bounding_box().size
        return getattr(size, key) * ureg.mm

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
            rho = check_density(density_g_per_cm3) * ureg.g / ureg.cm**3
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

    def _cylinder_radius(self, obj: str, kind: str | None = None, axis: str | None = None) -> Q:
        """Shared with the STEP adapter, not copied -- see `measurements.py`.

        Measured on the built geometry, not read from `BORE_RADIUS_MM`: the
        parameter says what the designer meant, the B-Rep what the script made.
        """
        return mm.cylinder_radius(self._part(obj), kind=kind, axis=axis)


_METHODS = {
    "bbox_size": Build123dAdapter._bbox_size,
    "volume": Build123dAdapter._volume,
    "mass": Build123dAdapter._mass,
    "face_count": Build123dAdapter._face_count,
    "cylinder_radius": Build123dAdapter._cylinder_radius,
}
