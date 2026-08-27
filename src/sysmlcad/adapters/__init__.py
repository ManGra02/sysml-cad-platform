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

`bbox_size` is deliberately not called "length". A bounding-box extent and a
named feature dimension are different things, and the difference only shows up
at the first draft angle. The mapping entry has to say which one it means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..units import Q


class Unsupported(Exception):
    """This adapter cannot supply that quantity for that object.

    Distinct from a wrong answer: callers report it as a gap in the model.
    """


@dataclass(frozen=True)
class Material:
    name: str
    density: Q | None = None


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
