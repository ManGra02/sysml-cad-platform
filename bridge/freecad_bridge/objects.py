"""Einzelne CAD-Objekte lesen.

Identitaet ist ausschliesslich ``obj.Name``. ``obj.ID`` reist als
Plausibilitaetspruefung mit -- es ist persistiert, aber nur pro Dokument
eindeutig. ``obj.Uid`` existiert nicht.

Abgeleitete Geometrie (Volume, BoundBox, ...) ist NIE Teil einer Standard-
antwort. Gemessen kostet ``Shape.Volume`` ueber 500 Boxen 0,07 s -- bei JEDEM
Aufruf, FreeCAD cacht das nicht. In einer Listenantwort waere das der Unter-
schied zwischen fluessig und unbenutzbar.
"""

import FreeCAD

from freecad_bridge import properties, revisions
from freecad_bridge.dispatch import BridgeError, main_thread_only
from freecad_bridge.documents import get_document

#: TypeIds, die FreeCAD selbst als Infrastruktur anlegt. Ein PartDesign-Body
#: mit einem Pad bringt 11 Objekte mit, davon 9 Origin-Zubehoer; 200 Bodies
#: waeren 1800 Achsen und Ebenen im Baum.
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
            "Objekt %r gibt es in %r nicht. Beachte: adressiert wird ueber Name, "
            "nicht ueber Label." % (obj_name, doc_name),
            {"doc": doc_name, "name": obj_name},
        )
    return obj


@main_thread_only
def is_internal(obj):
    return getattr(obj, "TypeId", "") in INTERNAL_TYPE_IDS


@main_thread_only
def summarize_object(obj):
    """Der schlanke Satz, der in Baum und Tabelle reicht."""
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

    # App::LinkElement ist eine Instanz eines Arrays, kein eigenstaendiges
    # Objekt. Ein App::Link mit ElementCount=200 erzeugt wirklich 202 Eintraege
    # in doc.Objects -- ohne diese Markierung waere der Baum unlesbar.
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
    """Ein Objekt mit allen Properties beschreiben."""
    data = summarize_object(obj)
    data["properties"] = properties.describe_properties(
        obj, fields=fields, include_internal=include_internal
    )
    if include_geometry:
        data["geometry"] = describe_geometry(obj)
    return data


@main_thread_only
def describe_geometry(obj):
    """Abgeleitete Geometriewerte -- teuer, deshalb nur auf Anforderung.

    Achtung: Shape.Mass ist NICHT die physikalische Masse, sondern die
    GProps-Masse bei Dichte 1. Sie fehlt ausserdem auf Part.Compound, ebenso
    CenterOfMass. Physikalische Masse = Dichte x Volume, siehe materials.py.
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

    # Auf Part.Compound fehlen CenterOfMass und Mass ganz -- kein Fehler,
    # sondern eine Eigenschaft des Typs.
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
    """Fehlende Werte weglassen statt die ganze Antwort scheitern zu lassen."""
    try:
        target[key] = getter()
    except Exception:
        pass


@main_thread_only
def list_objects(doc_name, names=None, fields=None, include_geometry=False,
                 include_internal=False):
    """Mehrere Objekte in EINER Dispatch-Runde.

    Ohne diese Route braeuchte eine Tabelle mit Property-Spalten N+1 Anfragen,
    jede mit eigenem Sprung auf den Hauptthread.
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
    """Darf ueber die HTTP-Schnittstelle erzeugt werden?

    Bewusst gefiltert: App::DocumentObjectFileIncluded zieht beliebige Dateien
    in das Dokument, und *FeaturePython*-Typen fuehren Python-Code aus dem
    Dokument aus. Beides gehoert nicht hinter eine offene HTTP-Route.
    """
    return "FeaturePython" not in type_name and type_name != "App::DocumentObjectFileIncluded"


@main_thread_only
def list_types():
    """Was in diesem Dokument erzeugt werden kann (siehe is_creatable)."""
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
