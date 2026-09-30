"""Read the properties of arbitrary CAD objects -- without knowing any CAD type.

This is the core of the platform: for every property FreeCAD provides enough
metadata (type, group, documentation, enumeration values, flags) to render it
generically. That is why the editor in the browser knows neither Part::Box nor
PartDesign::Pad.

CLASSIFICATION BY FAMILY, not by exact TypeId: there are 126 of those. The
mapping therefore goes by the Python type of the value, using the TypeId only
where it is needed (enumerations need their choices, links their shape).

Verified pitfalls handled here:
  * Label carries the status flag 'Output'. The naive rule "skip Output"
    would lock out renaming, of all things -> allow list.
  * Shape has status [] and can NOT be filtered via flags -> the decision
    depends on the TypeId.
  * Quantity.UserString is localized ('7900,00 kg/m^3') -> never serialize it.
  * Rotation.Angle is in radians -> quaternion for the round trip.
  * Spreadsheet cells appear in PropertiesList; a sheet with 20,000
    cells would produce a ~10 MB response -> separate route.
"""

import FreeCAD

from cad_contract import types
from freecad_bridge.dispatch import BridgeError, main_thread_only

#: Neither read nor write.
#: PropertyFileIncluded pulls an arbitrary user file into the document and
#: works as a path-existence oracle; PythonObject is arbitrary state.
DENYLIST_TYPE_IDS = frozenset(
    [
        "App::PropertyFile",
        "App::PropertyFileIncluded",
        "App::PropertyPythonObject",
    ]
)

#: Derived instead of serialized.
SHAPE_TYPE_IDS = frozenset(["Part::PropertyPartShape"])

#: Writable despite status flags. Label is 'Output' -- without this list
#: nothing could be renamed.
WRITABLE_ALLOWLIST = frozenset(["Label", "Label2", "Visibility"])

#: Flags that forbid writing (unless in the allow list).
BLOCKING_FLAGS = frozenset(["ReadOnly", "Output", "Transient"])

#: Internal bookkeeping. Fires along with every geometry change and means
#: nothing to the user.
INTERNAL_PREFIXES = ("_",)

#: Spreadsheet cells: A1, BC42 ... -- via a separate route, not generically.
_CELL_MAX_COLUMN_LETTERS = 3


def _is_cell_name(name):
    letters = 0
    for index, char in enumerate(name):
        if char.isalpha() and char.isupper():
            letters += 1
            continue
        if index == 0 or letters == 0 or letters > _CELL_MAX_COLUMN_LETTERS:
            return False
        return name[index:].isdigit()
    return False


def is_internal(name):
    return name.startswith(INTERNAL_PREFIXES)


# -- Encoding ----------------------------------------------------------


def _ref_from_object(obj, subs=None):
    return types.obj_ref(obj.Document.Name, obj.Name, subs)


def _encode_quantity(value):
    """Unit as a symbol, not as FreeCAD's repr.

    str(Unit) yields 'Unit: mm (1,0,0,0,0,0,0,0) [Length]' -- useless in the
    browser. The symbol follows the numeric value in the text; the kind of
    quantity comes from Unit.Type.
    """
    text = str(value)
    parts = text.split(" ", 1)
    symbol = parts[1].strip() if len(parts) == 2 else ""

    try:
        unit_type = value.Unit.Type or None
    except Exception:
        unit_type = None

    return types.quantity(value.Value, symbol, text, unit_type)


def _encode_link_value(value):
    """Bring all 24 link variants into one shape.

    Returns (kind_fn, payload), or None if it is not a link.
    """
    if value is None:
        return types.link(None)

    if _is_document_object(value):
        return types.link(_ref_from_object(value))

    if isinstance(value, (list, tuple)):
        if not value:
            return types.link_list([])

        # (obj, ['Face1', ...]) -- a LinkSub
        if (
            len(value) == 2
            and _is_document_object(value[0])
            and isinstance(value[1], (list, tuple, str))
        ):
            subs = value[1]
            if isinstance(subs, str):
                subs = [subs]
            return types.link_sub(_ref_from_object(value[0], subs))

        if all(_is_document_object(item) for item in value):
            return types.link_list([_ref_from_object(item) for item in value])

        # [(obj, subs), (obj2, subs2)] -- LinkSubList
        refs = []
        for item in value:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                return None
            target, subs = item
            if not _is_document_object(target):
                return None
            if isinstance(subs, str):
                subs = [subs]
            refs.append(_ref_from_object(target, subs))
        return types.link_sub_list(refs)

    return None


def _is_document_object(value):
    return hasattr(value, "Name") and hasattr(value, "Document") and hasattr(value, "TypeId")


def encode_value(obj, name, type_id):
    """Bring a property value into contract form.

    Returns (status, value). status is ENCODED, DERIVED or UNSUPPORTED.
    """
    if type_id in DENYLIST_TYPE_IDS:
        return types.UNSUPPORTED, types.unsupported(type_id, "blocked for security reasons")

    if type_id in SHAPE_TYPE_IDS:
        return types.DERIVED, None  # via ?include=geometry

    try:
        value = getattr(obj, name)
    except Exception as exc:
        return types.UNSUPPORTED, types.unsupported(type_id, "not readable: %s" % type(exc).__name__)

    # An enumeration needs its choices -- the value alone is not enough.
    if type_id == "App::PropertyEnumeration":
        try:
            choices = obj.getEnumerationsOfProperty(name) or []
        except Exception:
            choices = []
        return types.ENCODED, types.enum(value, choices)

    if value is None:
        # Can be an empty link or simply nothing.
        if "Link" in type_id:
            return types.ENCODED, types.link(None)
        return types.ENCODED, None

    if isinstance(value, bool):
        return types.ENCODED, value
    if isinstance(value, FreeCAD.Units.Quantity):
        return types.ENCODED, _encode_quantity(value)
    if isinstance(value, FreeCAD.Placement):
        return types.ENCODED, types.placement(list(value.Base), list(value.Rotation.Q))
    if isinstance(value, FreeCAD.Rotation):
        return types.ENCODED, types.rotation(list(value.Q))
    if isinstance(value, FreeCAD.Vector):
        return types.ENCODED, types.vector(value.x, value.y, value.z)
    if isinstance(value, FreeCAD.Matrix):
        return types.ENCODED, types.matrix(list(value.A))
    if isinstance(value, (int, float, str)):
        return types.ENCODED, value
    if isinstance(value, set):
        return types.ENCODED, types.value_set(value)
    if isinstance(value, dict):
        if all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            return types.ENCODED, types.mapping(value)
        return types.UNSUPPORTED, types.unsupported(type_id, "mapping with mixed types")

    material = _encode_material(value)
    if material is not None:
        return types.ENCODED, material

    if _is_document_object(value) or isinstance(value, (list, tuple)):
        encoded = _encode_link_value(value)
        if encoded is not None:
            return types.ENCODED, encoded
        encoded = _encode_simple_sequence(value, type_id)
        if encoded is not None:
            return types.ENCODED, encoded

    return types.UNSUPPORTED, types.unsupported(type_id, _summarize(value))


def _encode_material(value):
    """Materials::PropertyMaterial travels as a UUID, just as FreeCAD stores it."""
    uuid = getattr(value, "UUID", None)
    if uuid is None:
        return None
    return types.material_ref(uuid, getattr(value, "Name", "") or "")


def _encode_simple_sequence(value, type_id):
    """Lists of simple values, vectors or placements."""
    encoded = []
    for item in value:
        if isinstance(item, bool) or isinstance(item, (int, float, str)):
            encoded.append(item)
        elif isinstance(item, FreeCAD.Vector):
            encoded.append(types.vector(item.x, item.y, item.z))
        elif isinstance(item, FreeCAD.Placement):
            encoded.append(types.placement(list(item.Base), list(item.Rotation.Q)))
        elif isinstance(item, (list, tuple)) and all(
            isinstance(part, (int, float)) for part in item
        ):
            encoded.append(list(item))  # e.g. colors
        else:
            return None
    return encoded


def _summarize(value):
    """A short hint instead of repr().

    repr(FemMesh) would be a complete mesh dump, repr(Proxy) would contain a
    memory address that changes on every start.
    """
    name = type(value).__name__
    try:
        length = len(value)
    except TypeError:
        return name
    return "%s with %d entries" % (name, length)


# -- Metadata ----------------------------------------------------------


def _flags(obj, name):
    try:
        return list(obj.getTypeOfProperty(name))
    except Exception:
        return []


def _is_dynamic(obj, name):
    """Dynamic properties carry status code 21.

    getPropertyStatus() returns raw ints for a concrete property; the
    NAMES come from getTypeOfProperty(). There is no name for 'dynamic',
    so here, as an exception, the code is used.
    """
    try:
        return 21 in obj.getPropertyStatus(name)
    except Exception:
        return False


def _expression_for(obj, name):
    try:
        engine = obj.ExpressionEngine
    except Exception:
        return None
    for path, expression in engine or []:
        if path == name:
            return expression
    return None


def _is_writable(name, type_id, status, flags, expression):
    if status != types.ENCODED:
        return False
    if type_id in DENYLIST_TYPE_IDS or type_id in SHAPE_TYPE_IDS:
        return False
    if expression:
        return False  # would be overwritten on the next recompute
    if name in WRITABLE_ALLOWLIST:
        return True
    return not any(flag in BLOCKING_FLAGS for flag in flags)


@main_thread_only
def describe_property(obj, name):
    """Describe a property completely."""
    try:
        type_id = obj.getTypeIdOfProperty(name)
    except Exception:
        type_id = "unknown"

    status, value = encode_value(obj, name, type_id)
    flags = _flags(obj, name)
    expression = _expression_for(obj, name)

    try:
        group = obj.getGroupOfProperty(name)
    except Exception:
        group = None
    try:
        documentation = obj.getDocumentationOfProperty(name)
    except Exception:
        documentation = None

    return types.property_entry(
        name=name,
        type_id=type_id,
        status=status,
        value=value,
        group=group,
        doc=documentation,
        flags=flags,
        writable=_is_writable(name, type_id, status, flags, expression),
        dynamic=_is_dynamic(obj, name),
        expression=expression,
    )


@main_thread_only
def property_names(obj, include_internal=False):
    """Relevant property names of an object.

    Spreadsheet cells are excluded: they appear in PropertiesList, but
    belong to a separate range route.
    """
    try:
        names = list(obj.PropertiesList)
    except Exception:
        return []

    is_sheet = getattr(obj, "TypeId", "").startswith("Spreadsheet::")
    result = []
    for name in names:
        if not include_internal and is_internal(name):
            continue
        if is_sheet and _is_cell_name(name):
            continue
        result.append(name)
    return sorted(result)


@main_thread_only
def describe_properties(obj, fields=None, include_internal=False):
    """Describe all (or selected) properties.

    ``fields`` limits to an explicit list -- this is the path for the
    batch route, so that a table with three columns does not transfer the
    whole object.
    """
    names = property_names(obj, include_internal=include_internal)
    if fields is not None:
        wanted = set(fields)
        names = [name for name in names if name in wanted]
    return [describe_property(obj, name) for name in names]


# -- Decoding (M3) -----------------------------------------------------


class InvalidValue(BridgeError):
    """The value does not fit the property -- nothing was written.

    ``detail`` is machine-readable so the UI can build the message in the
    user's language: ``{field, reason, ...params}``. ``message`` is the
    English plain-text form (the API's language).
    """

    code = "invalid_value"
    http_status = 400

    def __init__(self, message, field=None, reason="invalid", **params):
        detail = {"field": field, "reason": reason}
        detail.update(params)
        super(InvalidValue, self).__init__(message, detail)


class NotWritable(BridgeError):
    code = "not_writable"
    http_status = 409


class ExpressionBound(BridgeError):
    """A literal value would be silently discarded on the next recompute."""

    code = "expression_bound"
    http_status = 409


def _payload_form(payload, kind):
    """Recognize the contract form ({"kind": ...}), otherwise None."""
    if isinstance(payload, dict) and payload.get("kind") == kind:
        return payload
    return None


def _resolve_ref(doc, ref, name):
    if ref is None:
        return None
    if not isinstance(ref, dict) or "name" not in ref:
        raise InvalidValue("%s: reference needs {doc, name}" % name, name, "ref_invalid")
    target_doc = doc
    if ref.get("doc") and ref["doc"] != doc.Name:
        try:
            target_doc = FreeCAD.getDocument(ref["doc"])
        except Exception:
            target_doc = None
        if target_doc is None:
            # No loading on demand: that would be a multi-second block in dispatch.
            raise InvalidValue(
                "%s: target document %r is not open" % (name, ref["doc"]),
                name, "target_doc_not_open", doc=ref["doc"],
            )
    target = target_doc.getObject(ref["name"])
    if target is None:
        raise InvalidValue(
            "%s: object %r not found (reference by Name, not Label)" % (name, ref["name"]),
            name, "target_not_found", target=ref["name"],
        )
    return target


def _decode_quantity(name, current, payload):
    form = _payload_form(payload, types.QUANTITY)
    if form is not None:
        payload = form.get("text") or form.get("value")
    if isinstance(payload, bool):
        raise InvalidValue("%s: quantity expected" % name, name, "quantity_expected")
    if isinstance(payload, (int, float)):
        return float(payload)  # in FreeCAD's internal units
    if not isinstance(payload, str):
        raise InvalidValue("%s: quantity expected" % name, name, "quantity_expected")
    try:
        quantity = FreeCAD.Units.Quantity(payload)
    except Exception:
        raise InvalidValue("%s: %r is not a valid quantity" % (name, payload), name, "quantity_invalid", input=payload)
    # A bare number as text ("25") is dimensionless and is taken as the
    # internal unit. Everything else must match the kind of quantity --
    # otherwise FreeCAD would answer "3 kg" on a length with ArithmeticError.
    dimensionless = tuple(quantity.Unit.Signature) == (0,) * 8
    if not dimensionless and tuple(quantity.Unit.Signature) != tuple(current.Unit.Signature):
        raise InvalidValue(
            "%s: unit does not match, expected %s" % (name, current.Unit.Type or "dimensionless"),
            name, "unit_mismatch", expected=current.Unit.Type or None,
        )
    return quantity.Value if dimensionless else quantity


def _decode_links(doc, name, payload):
    kind = payload.get("kind")
    if kind == types.LINK:
        return _resolve_ref(doc, payload.get("ref"), name)
    if kind == types.LINK_LIST:
        return [_resolve_ref(doc, ref, name) for ref in payload.get("refs", [])]
    if kind == types.LINK_SUB:
        ref = payload.get("ref")
        target = _resolve_ref(doc, ref, name)
        return (target, list(ref.get("subs", []))) if target is not None else None
    if kind == types.LINK_SUB_LIST:
        return [
            (_resolve_ref(doc, ref, name), list(ref.get("subs", [])))
            for ref in payload.get("refs", [])
        ]
    return _NO_MATCH


_NO_MATCH = object()


def _decode_value(obj, name, type_id, current, payload):
    """Decide from the CURRENT value which form is expected."""
    if type_id == "App::PropertyEnumeration":
        value = payload.get("value") if isinstance(payload, dict) else payload
        # A LIST would replace the choices instead of selecting one.
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise InvalidValue("%s: enumeration expects str or int" % name, name, "enum_type")
        choices = obj.getEnumerationsOfProperty(name) or []
        if isinstance(value, str) and value not in choices:
            raise InvalidValue(
                "%s: %r is not an allowed choice" % (name, value),
                name, "enum_choice", value=value, choices=choices,
            )
        if isinstance(value, int) and not 0 <= value < len(choices):
            raise InvalidValue("%s: index %d out of range" % (name, value), name, "enum_index", index=value)
        return value

    if isinstance(current, bool):
        if not isinstance(payload, bool):
            raise InvalidValue("%s: boolean expected" % name, name, "bool_expected")
        return payload

    if isinstance(current, FreeCAD.Units.Quantity):
        return _decode_quantity(name, current, payload)

    if isinstance(current, FreeCAD.Placement):
        form = _payload_form(payload, types.PLACEMENT)
        if form is None or len(form.get("pos") or []) != 3 or len(form.get("q") or []) != 4:
            raise InvalidValue("%s: {kind: placement, pos[3], q[4]} expected" % name, name, "form_expected", form="placement")
        return FreeCAD.Placement(FreeCAD.Vector(*form["pos"]), FreeCAD.Rotation(*form["q"]))

    if isinstance(current, FreeCAD.Rotation):
        form = _payload_form(payload, types.ROTATION)
        if form is None or len(form.get("q") or []) != 4:
            raise InvalidValue("%s: {kind: rotation, q[4]} expected" % name, name, "form_expected", form="rotation")
        return FreeCAD.Rotation(*form["q"])

    if isinstance(current, FreeCAD.Vector):
        form = _payload_form(payload, types.VECTOR)
        if form is None:
            raise InvalidValue("%s: {kind: vector, x, y, z} expected" % name, name, "form_expected", form="vector")
        return FreeCAD.Vector(form["x"], form["y"], form["z"])

    if isinstance(current, int):
        if isinstance(payload, bool) or not isinstance(payload, int):
            raise InvalidValue("%s: integer expected" % name, name, "int_expected")
        return payload

    if isinstance(current, float):
        if isinstance(payload, bool) or not isinstance(payload, (int, float)):
            raise InvalidValue("%s: number expected" % name, name, "number_expected")
        return float(payload)

    if type_id == "App::PropertyStringList":
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise InvalidValue("%s: list of strings expected" % name, name, "string_list_expected")
        return list(payload)

    if isinstance(current, str):
        if not isinstance(payload, str):
            raise InvalidValue("%s: text expected" % name, name, "text_expected")
        return payload

    if isinstance(payload, dict):
        decoded = _decode_links(obj.Document, name, payload)
        if decoded is not _NO_MATCH:
            return decoded
        kind = payload.get("kind")
        if kind == types.MAP:
            entries = payload.get("entries") or {}
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in entries.items()):
                raise InvalidValue("%s: map str -> str expected" % name, name, "map_expected")
            return dict(entries)
        if kind == types.MATERIAL_REF:
            try:
                import Materials

                return Materials.MaterialManager().getMaterial(payload.get("uuid"))
            except Exception:
                raise InvalidValue(
                    "%s: unknown material %r" % (name, payload.get("uuid")),
                    name, "material_unknown", uuid=payload.get("uuid"),
                )

    raise InvalidValue("%s: value form not supported for %s" % (name, type_id), name, "form_unsupported", typeId=type_id)


@main_thread_only
def decode_for_write(obj, name, payload):
    """Check whether ``name`` is writable, and build the FreeCAD value.

    Called for ALL fields BEFORE the transaction is opened: an invalid field
    should touch nothing, rather than having to roll back a half-applied
    change.
    """
    if name not in obj.PropertiesList or is_internal(name):
        raise InvalidValue("%s: unknown property" % name, name, "unknown_property")

    entry = describe_property(obj, name)
    if entry["expression"]:
        raise ExpressionBound(
            "%s is bound to the expression %r" % (name, entry["expression"]), name
        )
    if not entry["writable"]:
        raise NotWritable("%s is not writable (%s)" % (name, entry["typeId"]), name)

    return _decode_value(obj, name, entry["typeId"], getattr(obj, name), payload)
