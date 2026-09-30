"""The value format on the wire.

Dependency-free and importable both in FreeCAD's 3.11 and in the backend venv.
This defines WHAT something looks like -- not how it is fetched from FreeCAD.
The conversion lives in freecad_bridge.properties.

THREE OUTCOMES for every property, never more:

  encoded      A defined format that the editor can render and
               write back.
  derived      Derived, read-only (Shape -> Volume/BoundBox/ShapeType).
  unsupported  Present, but not editable here. The UI states
               this honestly.

There is deliberately NO str() fallback. repr() of a FEM mesh is a
complete mesh dump, and repr() of a proxy object contains a
memory address that changes on every start -- the cache would then
constantly see changes that are not real changes.
"""

# -- Kind markers for encoded values ----------------------------------

QUANTITY = "quantity"
VECTOR = "vector"
PLACEMENT = "placement"
ROTATION = "rotation"
MATRIX = "matrix"
COLOR = "color"
ENUM = "enum"
LINK = "link"
LINK_LIST = "link_list"
LINK_SUB = "link_sub"
LINK_SUB_LIST = "link_sub_list"
MATERIAL_REF = "material_ref"
MAP = "map"
SET = "set"
UNSUPPORTED = "unsupported"

#: Status of a property in transport.
ENCODED = "encoded"
DERIVED = "derived"


def obj_ref(doc, name, subs=None):
    """The ONLY key for an object across the process boundary.

    Always (doc.Name, obj.Name) -- both immutable and unique per
    document. NEVER obj.Label: that is a pure display field and not
    unique. In AssemblyExample.FCStd the object named 'Shape001' carries
    the label 'Base', while a DIFFERENT object is named 'Base' -- a
    label-as-name request silently patches the wrong object, without a 404.
    """
    ref = {"doc": doc, "name": name}
    if subs:
        ref["subs"] = list(subs)
    return ref


# -- Value shapes ------------------------------------------------------


def quantity(value, unit, text, unit_type=None):
    """Quantity with unit.

    ``value``     always in FreeCAD's INTERNAL units (mm, kg, s, degrees)
    ``unit``      the symbol for display ('mm', 'kg/mm^3'), empty if dimensionless
    ``unit_type`` the kind of quantity ('Length', 'Density') -- so the UI
                  can choose a suitable input field
    ``text``      the lossless round-trip form, str(Quantity)

    NEVER use UserString: it is localized ('7900,00 kg/m^3') and therefore
    neither comparable nor parsable back.
    """
    return {
        "kind": QUANTITY,
        "value": value,
        "unit": unit,
        "unitType": unit_type,
        "text": text,
    }


def vector(x, y, z):
    return {"kind": VECTOR, "x": x, "y": y, "z": z}


def placement(position, quaternion):
    """Placement as position + quaternion.

    Quaternion, not yaw-pitch-roll: Rotation.Angle is in radians, and only
    via .Q is the round trip lossless.
    """
    return {"kind": PLACEMENT, "pos": list(position), "q": list(quaternion)}


def rotation(quaternion):
    return {"kind": ROTATION, "q": list(quaternion)}


def matrix(values):
    return {"kind": MATRIX, "a": list(values)}


def color(rgba):
    return {"kind": COLOR, "rgba": list(rgba)}


def enum(value, choices):
    """Enumeration.

    When writing, send only str or int: a LIST replaces the choices
    instead of selecting one.
    """
    return {"kind": ENUM, "value": value, "choices": list(choices or [])}


def link(ref):
    return {"kind": LINK, "ref": ref}


def link_list(refs):
    return {"kind": LINK_LIST, "refs": list(refs)}


def link_sub(ref):
    return {"kind": LINK_SUB, "ref": ref}


def link_sub_list(refs):
    return {"kind": LINK_SUB_LIST, "refs": list(refs)}


def material_ref(uuid, name):
    """Material travels as a UUID.

    FreeCAD likewise persists ShapeMaterial only as a UUID -- self-created
    materials do not survive save/load.
    """
    return {"kind": MATERIAL_REF, "uuid": uuid, "name": name}


def mapping(pairs):
    return {"kind": MAP, "entries": dict(pairs)}


def value_set(values):
    return {"kind": SET, "values": sorted(values)}


def unsupported(type_id, summary):
    """Present, but not transportable. Honest instead of str()."""
    return {"kind": UNSUPPORTED, "typeId": type_id, "summary": summary}


# -- Property description ----------------------------------------------


def property_entry(name, type_id, status, value, group=None, doc=None,
                   flags=(), writable=False, dynamic=False, expression=None):
    """A property along with everything the generic editor needs to render it."""
    return {
        "name": name,
        "typeId": type_id,
        "status": status,          # ENCODED | DERIVED | UNSUPPORTED
        "value": value,
        "group": group,
        "doc": doc,
        "flags": list(flags),
        "writable": bool(writable),
        "dynamic": bool(dynamic),
        "expression": expression,  # bound -> writing would have no effect
    }


# -- Operations of a batch (POST .../operations) ------------------------

OP_CREATE = "create"
OP_DELETE = "delete"
OP_PATCH = "patch"
OP_SET_EXPRESSION = "set_expression"
OP_SET_CELLS = "set_cells"
OP_ADD_PROPERTY = "add_property"
OP_REMOVE_PROPERTY = "remove_property"

OPERATIONS = (
    OP_CREATE,
    OP_DELETE,
    OP_PATCH,
    OP_SET_EXPRESSION,
    OP_SET_CELLS,
    OP_ADD_PROPERTY,
    OP_REMOVE_PROPERTY,
)
