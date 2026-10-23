"""The CAD side, behind one seam: what an adapter offers and what it may answer.

Everything above this module speaks adapters and pint quantities -- never the bridge
directly. Today there is one adapter (freecad_snapshot.FreeCADSnapshot, FreeCAD through
the platform's bridge); the seam is what lets another CAD source join later without
touching gates, verification or proposers.

MEASUREMENT VOCABULARY -- part of the mapping language, adapter-independent.
An adapter implements what it can and raises ``Unsupported`` for the rest, never a
substituted value:

    bbox_size(axis="X")   extent of the axis-aligned bounding box
    volume()              solid volume
    mass()                volume times the density of the object's material
    face_count()          topological count, for geometry regression checks
    cylinder_radius(kind=None, axis=None)
                          radius of the ONE cylindrical feature -- a bore (kind="hole")
                          or a shaft/fillet (kind="boss"); several left is Unsupported
    parameter(name)       a named parameter, read rather than measured
                          (``Params.Length``, ``Pad.Length``): what the designer stated

``bbox_size`` is deliberately not called "length": a bounding-box extent and a named
feature dimension differ at the first draft angle or rotation.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field

from app.projects.bds.units import Q

METHODS = ("bbox_size", "volume", "mass", "face_count", "cylinder_radius", "parameter")

#: Methods a target offers only when it has something for them.
NEEDS_PARAMETERS = ("parameter",)


class Unsupported(Exception):
    """This adapter cannot supply that quantity for that object -- reported as a gap."""


def check_args(method, fn, *leading, **args):
    """Refuse ``args`` that ``fn`` does not take, before calling it.

    ``args:`` comes from a hand-edited mapping entry: a typo there is one gap,
    not a TypeError that takes every other verdict down with it.
    """
    try:
        inspect.signature(fn).bind(*leading, **args)
    except TypeError as exc:
        raise Unsupported("%s: %s" % (method, exc)) from None


def check_density(density_g_per_cm3):
    """A density override has to be a positive number -- zero would make every mass
    requirement pass with 0 kg."""
    if isinstance(density_g_per_cm3, bool) or not isinstance(density_g_per_cm3, (int, float)):
        raise Unsupported("mass: density_g_per_cm3 must be a number, not %r" % (density_g_per_cm3,))
    if not density_g_per_cm3 > 0:
        raise Unsupported("mass: density_g_per_cm3 must be positive, not %r" % (density_g_per_cm3,))
    return float(density_g_per_cm3)


@dataclass(frozen=True)
class Material:
    name: str
    density: Q | None = None


@dataclass(frozen=True)
class CadTarget:
    """One addressable thing on the CAD side, as a proposer sees it.

    ``reference`` is exactly what a mapping entry's ``cad_object:`` takes;
    ``name`` is what it is called (the label), which is what a proposer compares
    against a SysML part. ``methods`` are those it actually supports -- ``mass`` is
    absent without a material, because proposing it would only produce a gap.
    """

    adapter: str
    reference: str
    kind: str                                  # part | assembly
    name: str = ""
    methods: tuple = METHODS
    parameters: dict = field(default_factory=dict)
    note: str = ""
    depth: int = 0
    container: str = ""                        # reference of the enclosing assembly

    @property
    def addressable(self):
        return bool(self.methods)

    def to_dict(self):
        return {"adapter": self.adapter, "reference": self.reference, "kind": self.kind,
                "name": self.name, "methods": list(self.methods), "note": self.note,
                "depth": self.depth, "container": self.container or None,
                "parameters": {k: format(v, "~P") for k, v in sorted(self.parameters.items())}}


@dataclass(frozen=True)
class LimitChange:
    """One requirement limit as it is in the CAD document (``old``, None if absent)
    and as it will be."""

    alias: str
    old: Q | None
    new: Q


class AdapterPool:
    """The adapters of one run, by the name a mapping entry's ``adapter:`` uses."""

    def __init__(self, adapters=None):
        self._adapters = dict(adapters or {})

    def get(self, name):
        if name not in self._adapters:
            raise Unsupported("unknown CAD adapter %r (available: %s)"
                              % (name, ", ".join(sorted(self._adapters)) or "none"))
        return self._adapters[name]

    @property
    def names(self):
        return ",".join(sorted(self._adapters))

    @property
    def state_id(self):
        return ",".join("%s:%s" % (name, adapter.state_id())
                        for name, adapter in sorted(self._adapters.items()))
