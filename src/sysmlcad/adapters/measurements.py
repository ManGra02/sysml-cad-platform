"""The measurement vocabulary, over a build123d/OCCT shape.

These are the same methods `adapters/__init__.py` documents. They live here as
free functions so a file-based adapter can use them without owning a CAD
kernel of its own.

The first four are deliberately NOT wired into `Build123dAdapter`: adding STEP
support is an add-on, and rewiring code that already works is how add-ons lose
features. The cost is that their semantics exist twice and could drift, so
`tests/test_step_adapter.py` pays for it instead -- it measures the same
geometry through both adapters and asserts the results agree. Merging the two
is a separate, clearly scoped step once the STEP path has proven itself.

`cylinder_radius` came later and exists only here: both adapters call it, so
there is nothing to drift and nothing for a test to hold together.
"""

from __future__ import annotations

from build123d import Shape, Vector
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder

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
    key = str(axis).upper()
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


#: Two cylindrical faces belong to the same feature when radius and axis line
#: agree to this, in mm. A bore split by a seam, or running through two parts
#: of an assembly, is one feature; a second bore a micrometre off is not.
_SAME_CYLINDER_MM = 1e-4

_AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
_KINDS = ("hole", "boss")


def cylinder_radius(shape: Shape, kind: str | None = None, axis: str | None = None) -> Q:
    """Radius of the ONE cylindrical feature of a shape.

    Measured on the B-Rep, so it works on a STEP file as well as on a script:
    every face whose surface is a cylinder, grouped into features by radius and
    axis line. `kind` keeps only bores (`hole`, material outside the surface)
    or only shafts and fillets (`boss`, material inside); `axis` keeps only
    cylinders whose axis is parallel to that model axis.

    Exactly one feature has to remain. None is a gap; several is an error,
    never a choice -- returning the first would be a plausible number from the
    wrong feature, which is the failure this project exists to prevent. A
    fillet is a cylinder too, so a rounded part needs `kind` or `axis` to say
    which one is meant.
    """
    if kind is not None and kind not in _KINDS:
        raise Unsupported(f"cylinder_radius: kind must be hole or boss, not {kind!r}")
    direction = None
    if axis is not None:
        direction = _AXES.get(str(axis).upper())
        if direction is None:
            raise Unsupported(f"cylinder_radius: axis must be X, Y or Z, not {axis!r}")

    features: list[dict] = []
    for face in shape.faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Cylinder:
            continue
        cylinder = surface.Cylinder()
        line = cylinder.Axis()
        origin = Vector(line.Location().X(), line.Location().Y(), line.Location().Z())
        along = Vector(line.Direction().X(), line.Direction().Y(), line.Direction().Z())

        # Which side the material is on. The face normal respects the face's
        # orientation and points out of the material; towards the axis means a
        # bore. The face's orientation flag alone does not say this -- a
        # fillet's can read either way, depending on its surface's direction.
        point = face.position_at(0.5, 0.5)
        offset = point - origin
        radial = offset - along * offset.dot(along)
        face_kind = "hole" if face.normal_at(0.5, 0.5).dot(radial) < 0 else "boss"

        if kind is not None and face_kind != kind:
            continue
        if direction is not None and abs(abs(along.dot(Vector(*direction))) - 1) > 1e-9:
            continue

        feature = {"radius": cylinder.Radius(), "origin": origin, "along": along,
                   "kind": face_kind}
        if not any(_same_cylinder(feature, known) for known in features):
            features.append(feature)

    narrowed = ", ".join(
        f"{name}={value}" for name, value in (("kind", kind), ("axis", axis)) if value
    )
    if not features:
        raise Unsupported(
            "cylinder_radius: no cylindrical face"
            + (f" with {narrowed}" if narrowed else "")
        )
    if len(features) > 1:
        found = ", ".join(
            f"{f['kind']} r={f['radius']:.4g} mm along "
            f"({f['along'].X:.3g}, {f['along'].Y:.3g}, {f['along'].Z:.3g})"
            for f in features
        )
        raise Unsupported(
            f"cylinder_radius: {len(features)} cylindrical features"
            + (f" with {narrowed}" if narrowed else "")
            + f" ({found}) -- narrow it with kind or axis, which one is meant "
            f"is not the adapter's to decide"
        )
    return features[0]["radius"] * _LENGTH


def _same_cylinder(a: dict, b: dict) -> bool:
    """Same radius, same kind, and the same axis LINE -- parallel is not enough."""
    if a["kind"] != b["kind"] or abs(a["radius"] - b["radius"]) > _SAME_CYLINDER_MM:
        return False
    if abs(abs(a["along"].dot(b["along"])) - 1) > 1e-9:
        return False
    offset = b["origin"] - a["origin"]
    off_line = offset - a["along"] * offset.dot(a["along"])
    return off_line.length <= _SAME_CYLINDER_MM
