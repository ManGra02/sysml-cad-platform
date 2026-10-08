"""The CAD side, behind one seam.

Nothing above this package may import build123d, FreeCAD, or any other
geometry kernel. Everything above speaks `CadAdapter` and pint quantities.
That rule is the whole point: the SRS (FREQ-2) describes a live CAD document
with an assembly tree, named parameters and assigned materials, which is a
FreeCAD/CATIA/Onshape shape, not a build123d one. Keeping the kernel behind an
interface is what lets the verification engine outlive the choice.

MEASUREMENT VOCABULARY
----------------------
Method names are part of the mapping language and are adapter-independent.
Every adapter implements what it can and raises `Unsupported` for the rest --
never a substituted value. SRS FREQ-2: "Where a property cannot be computed,
[...] the system reports the gap instead of substituting a value."

    bbox_size(axis="X")   extent of the axis-aligned bounding box
    volume()              solid volume from the B-Rep
    mass()                volume times density; density comes from the
                          object's material unless overridden in `args`
    face_count()          topological count, for geometry regression tests
    cylinder_radius(kind=None, axis=None)
                          radius of the one cylindrical feature -- a bore
                          (kind="hole") or a shaft/fillet (kind="boss"); more
                          than one left after narrowing is Unsupported

METHODS is that vocabulary as data, so a catalogue can list what an adapter
offers without every caller repeating the names.

`bbox_size` is deliberately not called "length". A bounding-box extent and a
named feature dimension are different things, and the difference only shows up
at the first draft angle. The mapping entry has to say which one it means.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..units import Q

#: The measurement vocabulary, as data. Adapter-independent by design; an
#: adapter that cannot do one of these raises `Unsupported` rather than
#: quietly offering fewer.
METHODS = ("bbox_size", "volume", "mass", "face_count", "cylinder_radius")


class Unsupported(Exception):
    """This adapter cannot supply that quantity for that object.

    Distinct from a wrong answer: callers report it as a gap in the model.
    """


def check_args(method: str, fn, *leading, **args) -> None:
    """Refuse `args` that `fn` does not take, before calling it.

    `args:` comes from a hand-edited mapping entry, so a typo there is a mapping
    fault and must surface as `Unsupported` -- one gap -- rather than as a
    TypeError that takes every other verdict in the run down with it. Binding
    the signature instead of catching TypeError around the call keeps a genuine
    bug inside a measurement from being mistaken for a bad mapping.
    """
    try:
        inspect.signature(fn).bind(*leading, **args)
    except TypeError as exc:
        raise Unsupported(f"{method}: {exc}") from None


def check_density(density_g_per_cm3) -> float:
    """A density override has to be a positive number.

    Zero would make every mass requirement pass with a mass of 0 kg -- a
    confident, wrong verdict from a typo.
    """
    if isinstance(density_g_per_cm3, bool) or not isinstance(density_g_per_cm3, (int, float)):
        raise Unsupported(f"mass: density_g_per_cm3 must be a number, not {density_g_per_cm3!r}")
    if not density_g_per_cm3 > 0:
        raise Unsupported(f"mass: density_g_per_cm3 must be positive, not {density_g_per_cm3!r}")
    return float(density_g_per_cm3)


@dataclass(frozen=True)
class Material:
    name: str
    density: Q | None = None


@dataclass(frozen=True)
class CadTarget:
    """One addressable thing on the CAD side, as a mapping proposal would see it.

    This is the CAD half of the "structural excerpt of both models" SRS FREQ-4
    hands to a proposer. It is deliberately descriptive, not measured: listing
    a catalogue must not cost a full geometry build of every object.

    `reference` is exactly the string a mapping entry's `cad_object:` takes, so
    a proposal is copy-and-paste rather than reconstruction. `name` is the same
    thing stripped of its address -- `Housing`, not
    `fixtures/step/gearbox.step#Housing` -- because a name is what a proposal
    can compare against a SysML part, and a file path is not.

    `methods` are the ones this target actually supports -- `mass` is absent
    when the object carries no material, because proposing it would only
    produce a gap.
    """

    adapter: str
    reference: str
    kind: str                                  # part | assembly | module
    name: str = ""                             # what it is called, not where it is
    methods: tuple[str, ...] = METHODS
    parameters: dict[str, Q] = field(default_factory=dict)
    note: str = ""
    depth: int = 0                             # nesting in the assembly tree

    @property
    def addressable(self) -> bool:
        """False when nothing can be measured here -- an ambiguous name, say.
        Listed rather than dropped, because "this exists but you cannot point at
        it" is information a proposer and a human both need."""
        return bool(self.methods)


@runtime_checkable
class CadAdapter(Protocol):
    """The contract the verification engine relies on."""

    #: Short identifier recorded in `RunContext.cad_adapter`.
    name: str

    def state_id(self) -> str:
        """An identifier for the current CAD state.

        Two runs with the same `state_id` measured the same geometry. It goes
        into the evidence record so a verdict can be tied to a design state,
        the way `sysml_commit_id` ties it to a requirement state.
        """
        ...

    def objects(self) -> list[str]:
        """The CAD objects this adapter can address, by stable reference."""
        ...

    def parameter(self, obj: str, name: str) -> Q | None:
        """A named parameter of the object, or None if it has no such name.

        Named parameters -- never face or edge indices. See the stable-identity
        convention in CLAUDE.md; indices move when the model is rebuilt.
        """
        ...

    def measure(self, obj: str, method: str, args: dict | None = None) -> Q:
        """Apply a measurement method from the vocabulary above."""
        ...

    def material(self, obj: str) -> Material | None:
        """The assigned material, or None when the object has none."""
        ...

    def catalog(self, objects: list[str] | None = None) -> list[CadTarget]:
        """What this adapter offers, as `CadTarget`s.

        `objects` names what to describe -- module names, file paths -- because
        where a project keeps its CAD files is not the adapter's business.
        Passing None means "whatever you already know about", which is what the
        adapter has loaded so far.
        """
        ...
