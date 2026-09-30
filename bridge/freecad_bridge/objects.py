"""Read individual CAD objects.

Identity is exclusively ``obj.Name``. ``obj.ID`` travels along as a
plausibility check -- it is persisted, but unique only per
document. ``obj.Uid`` does not exist.

Derived geometry (Volume, BoundBox, ...) is NEVER part of a standard
response. Measured: ``Shape.Volume`` over 500 boxes costs 0.07 s -- on EVERY
call, FreeCAD does not cache it. In a list response that would be the
difference between smooth and unusable.
"""

import FreeCAD

from freecad_bridge import properties, revisions
from freecad_bridge.dispatch import BridgeError, main_thread_only
from freecad_bridge.documents import get_document

#: TypeIds that FreeCAD itself creates as infrastructure. A PartDesign body
#: with one pad brings 11 objects, 9 of them origin accessories; 200 bodies
#: would be 1800 axes and planes in the tree.
INTERNAL_TYPE_IDS = frozenset(
    [
        "App::Origin",
        "App::Line",
        "App::Plane",
        "App::Point",
        "App::LocalCoordinateSystem",
        "PartDesign::CoordinateSystem",
        "PartDesign::Line",
        "PartDesign::Plane",
        "PartDesign::Point",
    ]
)


class ObjectNotFound(BridgeError):
    code = "object_not_found"
    http_status = 404


@main_thread_only
def get_object(doc_name, obj_name):
    doc = get_document(doc_name)
    obj = doc.getObject(obj_name)
    if obj is None:
        raise ObjectNotFound(
            "Object %r does not exist in %r. Note: objects are addressed by Name, "
            "not by Label." % (obj_name, doc_name),
            {"doc": doc_name, "name": obj_name},
        )
    return obj


@main_thread_only
def is_internal(obj):
    return getattr(obj, "TypeId", "") in INTERNAL_TYPE_IDS


@main_thread_only
def summarize_object(obj):
    """The lean set that suffices for tree and table."""
    entry = {
        "doc": obj.Document.Name,
        "name": obj.Name,
        "label": obj.Label,
        "typeId": obj.TypeId,
        "id": getattr(obj, "ID", None),
        "internal": is_internal(obj),
        "visible": _visibility(obj),
        "state": list(getattr(obj, "State", []) or []),
        "rev": revisions.current(obj.Document.Name, obj.Name),
    }

    # App::LinkElement is an instance of an array, not a standalone
    # object. An App::Link with ElementCount=200 really creates 202 entries
    # in doc.Objects -- without this marker the tree would be unreadable.
    if obj.TypeId == "App::LinkElement":
        entry["instanceOf"] = _link_element_parent(obj)
    return entry


def _visibility(obj):
    try:
        return bool(obj.Visibility)
    except Exception:
        return None


def _link_element_parent(obj):
    for parent in getattr(obj, "InList", []) or []:
        if getattr(parent, "TypeId", "") == "App::Link":
            return parent.Name
    return None


@main_thread_only
def describe_object(obj, fields=None, include_geometry=False, include_internal=False):
    """Describe an object with all its properties."""
    data = summarize_object(obj)
    data["properties"] = properties.describe_properties(
        obj, fields=fields, include_internal=include_internal
    )
    if include_geometry:
        data["geometry"] = describe_geometry(obj)
    return data


@main_thread_only
def describe_geometry(obj):
    """Derived geometry values -- expensive, therefore only on request.

    Caution: Shape.Mass is NOT the physical mass but the
    GProps mass at density 1. It is also missing on Part.Compound, as is
    CenterOfMass. Physical mass = density x Volume, see materials.py.
    """
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return None

    try:
        if shape.isNull():
            return {"shapeType": None, "null": True}
    except Exception:
        return None

    info = {"null": False}
    _collect(info, "shapeType", lambda: shape.ShapeType)
    _collect(info, "volume", lambda: shape.Volume)
    _collect(info, "area", lambda: shape.Area)
    _collect(info, "valid", lambda: bool(shape.isValid()))

    def bounding_box():
        box = shape.BoundBox
        return {
            "min": [box.XMin, box.YMin, box.ZMin],
            "max": [box.XMax, box.YMax, box.ZMax],
            "lengths": [box.XLength, box.YLength, box.ZLength],
            "center": [box.Center.x, box.Center.y, box.Center.z],
            "diagonal": box.DiagonalLength,
        }

    _collect(info, "boundBox", bounding_box)

    # On Part.Compound, CenterOfMass and Mass are missing entirely -- not an
    # error but a property of the type.
    _collect(info, "centerOfMass", lambda: list(shape.CenterOfMass))

    counts = {}
    for key, attribute in (
        ("solids", "Solids"),
        ("faces", "Faces"),
        ("edges", "Edges"),
        ("vertexes", "Vertexes"),
    ):
        _collect(counts, key, lambda a=attribute: len(getattr(shape, a)))
    if counts:
        info["counts"] = counts

    return info


def _collect(target, key, getter):
    """Omit missing values instead of letting the whole response fail."""
    try:
        target[key] = getter()
    except Exception:
        pass


@main_thread_only
def list_objects(doc_name, names=None, fields=None, include_geometry=False,
                 include_internal=False):
    """Several objects in ONE dispatch round.

    Without this route a table with property columns would need N+1 requests,
    each with its own hop onto the main thread.
    """
    doc = get_document(doc_name)

    if names:
        objects = []
        missing = []
        for name in names:
            obj = doc.getObject(name)
            if obj is None:
                missing.append(name)
            else:
                objects.append(obj)
    else:
        objects = list(doc.Objects)
        missing = []

    if not include_internal:
        objects = [obj for obj in objects if not is_internal(obj)]

    result = {
        "doc": doc_name,
        "objects": [
            describe_object(
                obj,
                fields=fields,
                include_geometry=include_geometry,
                include_internal=include_internal,
            )
            for obj in objects
        ],
    }
    if missing:
        result["missing"] = missing
    return result


def is_creatable(type_name):
    """May this be created via the HTTP interface?

    Deliberately filtered: App::DocumentObjectFileIncluded pulls arbitrary files
    into the document, and *FeaturePython* types execute Python code from the
    document. Neither belongs behind an open HTTP route.
    """
    return "FeaturePython" not in type_name and type_name != "App::DocumentObjectFileIncluded"


@main_thread_only
def list_types():
    """What can be created in this document (see is_creatable)."""
    doc = FreeCAD.activeDocument()
    if doc is None:
        doc = FreeCAD.newDocument("__typeprobe__", hidden=True, temp=True)
        try:
            names = list(doc.supportedTypes())
        finally:
            FreeCAD.closeDocument(doc.Name)
    else:
        names = list(doc.supportedTypes())

    allowed = [name for name in names if is_creatable(name)]
    return {"types": sorted(allowed), "excluded": sorted(set(names) - set(allowed))}
