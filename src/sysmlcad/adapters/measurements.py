"""The measurement vocabulary, over a build123d/OCCT shape.

These are the same four methods `adapters/__init__.py` documents. They live
here as free functions so a file-based adapter can use them without owning a
CAD kernel of its own.

Deliberately NOT wired into `Build123dAdapter`: adding STEP support is an
add-on, and rewiring code that already works is how add-ons lose features. The
cost is that the semantics now exist twice and could drift, so
`tests/test_step_adapter.py` pays for it instead -- it measures the same
geometry through both adapters and asserts the results agree. Merging the two
is a separate, clearly scoped step once the STEP path has proven itself.
"""

from __future__ import annotations

from build123d import Shape

from ..units import Q, ureg
from . import Unsupported

#: OCCT works in millimetres once the STEP reader has normalised the file's
#: declared unit. Everything below assumes that and says so.
_LENGTH = ureg.mm


def bbox_size(shape: Shape, axis: str = "X") -> Q:
    """Extent of the axis-aligned bounding box along a model axis.

    Not the same thing as a named feature dimension -- the difference shows up
    at the first draft angle. The mapping entry has to say which it means.
    """
    key = axis.upper()
    if key not in ("X", "Y", "Z"):
        raise Unsupported(f"bbox_size: axis must be X, Y or Z, not {axis!r}")
    return getattr(shape.bounding_box().size, key) * _LENGTH


def volume(shape: Shape) -> Q:
    """Solid volume from the B-Rep."""
    return shape.volume * _LENGTH**3


def mass(shape: Shape, density: Q) -> Q:
    """Volume times density. Homogeneous material assumed.

    The caller supplies the density; deciding where it comes from -- the
    file's material, or an override for a replacement-part study -- is the
    adapter's job, not this function's.
    """
    return (volume(shape) * density).to(ureg.kg)


def face_count(shape: Shape) -> Q:
    """Topological count, for geometry regression tests."""
    return len(shape.faces()) * ureg.dimensionless
