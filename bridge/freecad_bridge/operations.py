"""Several changes as ONE batch -- the write path for project modules.

A batch is a list of operations (create, delete, set properties, bind
expressions, set spreadsheet cells, add custom properties).
In FreeCAD it is exactly ONE undo step and applies all or nothing.

Established empirically on FreeCAD 1.1 before this file was written:
  * closeActiveTransaction(True) rolls back EVERYTHING: addObject, removeObject,
    addProperty/removeProperty, setExpression, cells and aliases.
  * addObject renames on collision ("Box" -> "Box001"). Later
    operations therefore refer via placeholders ("as": "m" -> "$m"), and the
    response reports the real names.
  * setExpression with a syntax error raises ParserError; an expression on an
    unknown alias does NOT raise, but makes the object 'Invalid' on
    recompute. Hence the check after the recompute ("strict").
  * Dynamic properties carry status 21 and can be removed,
    built-in ones cannot.
"""

import re

import FreeCAD

from cad_contract import types
from freecad_bridge import documents, log, objects, observer, properties, revisions, writes
from freecad_bridge import state as bridge_state
from freecad_bridge.dispatch import BridgeError, CadBusyError, main_thread_only

MAX_OPS = 200
MAX_EXPRESSION = 2048

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CELL_RE = re.compile(r"^[A-Z]{1,3}[0-9]{1,6}$")

#: Which property types a module may add itself -- simple values
#: that the editor can display and the bridge can write back.
DYNAMIC_PROPERTY_TYPES = frozenset(
    [
        "App::PropertyString",
        "App::PropertyStringList",
        "App::PropertyInteger",
        "App::PropertyFloat",
        "App::PropertyBool",
        "App::PropertyLength",
        "App::PropertyDistance",
        "App::PropertyAngle",
        "App::PropertyQuantity",
        "App::PropertyMap",
    ]
)

OPS = types.OPERATIONS


class OperationError(BridgeError):
    """Error in an operation -- carries the code and status of the cause."""

    def __init__(self, code, http_status, message, detail=None):
        super(OperationError, self).__init__(message, detail)
        self.code = code
        self.http_status = http_status


def _invalid(message, field=None):
    return OperationError("invalid_operation", 400, message, field)


class RecomputeFailed(BridgeError):
    code = "recompute_failed"
    http_status = 409


class HasDependents(BridgeError):
    code = "has_dependents"
    http_status = 409


# -- Validate before touching anything ----------------------------------


def _validate(ops):
    if not isinstance(ops, list) or not ops:
        raise _invalid("ops: at least one operation expected")
    if len(ops) > MAX_OPS:
        raise _invalid("At most %d operations per transaction" % MAX_OPS)
    aliases = set()
    for index, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise _invalid("Operation %d: unknown, allowed are %s" % (index, ", ".join(OPS)))
        alias = op.get("as")
        if alias is not None:
            if op["op"] != "create":
                raise _invalid("Operation %d: 'as' is only valid for create" % index)
            if not isinstance(alias, str) or not NAME_RE.match(alias) or alias in aliases:
                raise _invalid("Operation %d: placeholder %r invalid or duplicate" % (index, alias))
            aliases.add(alias)


def _resolve(doc, ref, aliases):
    """Object by name or placeholder ("$m") -- never by label."""
    if not isinstance(ref, str) or not ref:
        raise _invalid("Object expected (name or $placeholder)")
    if ref.startswith("$"):
        name = aliases.get(ref[1:])
        if name is None:
            raise _invalid("Placeholder %r has not been created (yet)" % ref)
        ref = name
    obj = doc.getObject(ref)
    if obj is None:
        raise objects.ObjectNotFound(
            "Object %r does not exist in %r (addressed by Name, not Label)" % (ref, doc.Name),
            {"doc": doc.Name, "name": ref},
        )
    return obj


def _precheck_revisions(doc, ops):
    """Check if_match BEFORE opening the transaction.

    check_revision flushes the observer -- in the middle of an open transaction
    that would send out half-finished events.
    """
    for op in ops:
        if op["op"] == "patch" and op.get("if_match") is not None:
            ref = op.get("obj")
            if isinstance(ref, str) and not ref.startswith("$"):
                writes.check_revision(_resolve(doc, ref, {}), op["if_match"])


# -- The operations -----------------------------------------------------


def _op_create(doc, op, aliases):
    type_name = op.get("type")
    if not isinstance(type_name, str) or "::" not in type_name:
        raise _invalid("create: type like 'Part::Box' expected, not %r" % (type_name,), "type")
    if not objects.is_creatable(type_name):
        raise OperationError("type_not_allowed", 403, "create: %s is blocked" % type_name, "type")

    name = op.get("name") or type_name.split("::")[-1]
    if not isinstance(name, str):
        raise _invalid("create: name must be text", "name")
    # Do not check against doc.supportedTypes(): a module's types (such as
    # Spreadsheet::Sheet) only appear there once the module is loaded --
    # addObject loads it itself.
    try:
        obj = doc.addObject(type_name, name)
    except Exception as exc:
        raise _invalid("create: unknown type %r (%s)" % (type_name, exc), "type")

    label = op.get("label")
    if label is not None:
        if not isinstance(label, str):
            raise _invalid("create: label must be text", "label")
        obj.Label = label

    group = op.get("group")
    if group is not None:
        container = _resolve(doc, group, aliases)
        if not container.hasExtension("App::GroupExtension"):
            raise _invalid("create: %s is not a container (group, part, body)" % container.Name, "group")
        container.addObject(obj)

    _set_props(obj, op.get("props") or {})

    if op.get("as"):
        aliases[op["as"]] = obj.Name
    return {"op": "create", "name": obj.Name, "label": obj.Label, "as": op.get("as")}


def _set_props(obj, props):
    if not isinstance(props, dict):
        raise _invalid("props: {Property: value} expected", "props")
    if not props:
        return []
    decoded = writes.decode_all(obj, props)
    changed = []
    for name, value in decoded.items():
        if writes.same_value(getattr(obj, name), value):
            continue
        setattr(obj, name, value)
        changed.append(name)
    return changed


def _dependents(obj):
    """Who depends on ``obj``? Mere container membership does not count."""
    result = []
    for other in obj.InList:
        if other.hasExtension("App::GroupExtension") and obj in (getattr(other, "Group", None) or []):
            continue
        result.append(other)
    return result


def _op_delete(doc, op, aliases):
    obj = _resolve(doc, op.get("obj"), aliases)
    dependents = _dependents(obj)
    if dependents and not op.get("force"):
        raise HasDependents(
            "%s is still used by %d object(s)" % (obj.Label, len(dependents)),
            {"dependents": [{"name": d.Name, "label": d.Label} for d in dependents]},
        )
    name = obj.Name
    doc.removeObject(name)
    return {"op": "delete", "name": name, "brokenDependents": [d.Name for d in dependents]}


def _op_patch(doc, op, aliases):
    obj = _resolve(doc, op.get("obj"), aliases)
    props = op.get("props")
    if not isinstance(props, dict) or not props:
        raise _invalid("patch: props expected", "props")
    changed = _set_props(obj, props)
    return {"op": "patch", "name": obj.Name, "changed": changed}


def _op_set_expression(doc, op, aliases):
    obj = _resolve(doc, op.get("obj"), aliases)
    prop = op.get("prop")
    if not isinstance(prop, str) or prop not in obj.PropertiesList or properties.is_internal(prop):
        raise _invalid("set_expression: unknown property %r" % (prop,), "prop")
    type_id = obj.getTypeIdOfProperty(prop)
    if type_id in properties.DENYLIST_TYPE_IDS or type_id in properties.SHAPE_TYPE_IDS:
        raise OperationError("not_writable", 409, "set_expression: %s cannot be bound" % prop, prop)

    expr = op.get("expr")
    if expr is not None and (not isinstance(expr, str) or not expr.strip()):
        raise _invalid("set_expression: expr must be text (null removes the expression)", "expr")
    if expr is not None and len(expr) > MAX_EXPRESSION:
        raise _invalid("set_expression: expression longer than %d characters" % MAX_EXPRESSION, "expr")
    try:
        obj.setExpression(prop, expr)
    except Exception as exc:
        raise OperationError(
            "invalid_expression", 400, "set_expression: %s -- %s" % (expr, exc), {"prop": prop, "expr": expr}
        )
    return {"op": "set_expression", "name": obj.Name, "prop": prop, "expr": expr}


def _sheet(doc, ref, aliases):
    sheet = _resolve(doc, ref, aliases)
    if not sheet.TypeId.startswith("Spreadsheet::Sheet"):
        raise _invalid("%s is not a spreadsheet (Spreadsheet::Sheet)" % sheet.Name, "sheet")
    return sheet


def _op_set_cells(doc, op, aliases):
    sheet = _sheet(doc, op.get("sheet"), aliases)
    cells = op.get("cells") or {}
    alias_map = op.get("aliases") or {}
    if not isinstance(cells, dict) or not isinstance(alias_map, dict) or not (cells or alias_map):
        raise _invalid("set_cells: cells and/or aliases expected", "cells")

    for cell, content in cells.items():
        if not isinstance(cell, str) or not CELL_RE.match(cell):
            raise _invalid("set_cells: invalid cell %r" % (cell,), "cells")
        if content is None:
            sheet.clear(cell)
        elif isinstance(content, bool) or not isinstance(content, (str, int, float)):
            raise _invalid("set_cells: %s needs text or a number" % cell, "cells")
        else:
            sheet.set(cell, str(content))

    for cell, alias in alias_map.items():
        if not isinstance(cell, str) or not CELL_RE.match(cell):
            raise _invalid("set_cells: invalid cell %r" % (cell,), "aliases")
        if alias is not None and (not isinstance(alias, str) or not NAME_RE.match(alias)):
            raise _invalid("set_cells: invalid alias %r" % (alias,), "aliases")
        try:
            sheet.setAlias(cell, alias or "")
        except Exception as exc:
            raise _invalid("set_cells: alias %r for %s: %s" % (alias, cell, exc), "aliases")

    return {"op": "set_cells", "name": sheet.Name, "cells": sorted(cells), "aliases": sorted(alias_map)}


def _op_add_property(doc, op, aliases):
    obj = _resolve(doc, op.get("obj"), aliases)
    type_id = op.get("type")
    name = op.get("name")
    if type_id not in DYNAMIC_PROPERTY_TYPES:
        raise _invalid(
            "add_property: type %r not allowed (%s)" % (type_id, ", ".join(sorted(DYNAMIC_PROPERTY_TYPES))), "type"
        )
    if not isinstance(name, str) or not NAME_RE.match(name) or name.startswith("_"):
        raise _invalid("add_property: invalid name %r" % (name,), "name")
    if name in obj.PropertiesList:
        raise OperationError("property_exists", 409, "add_property: %s.%s already exists" % (obj.Name, name), name)

    group = op.get("group") or "Plattform"
    documentation = op.get("doc") or ""
    if not isinstance(group, str) or not isinstance(documentation, str):
        raise _invalid("add_property: group and doc must be text", "group")
    obj.addProperty(type_id, name, group, documentation)

    if "value" in op:
        _set_props(obj, {name: op["value"]})
    return {"op": "add_property", "name": obj.Name, "prop": name}


def _op_remove_property(doc, op, aliases):
    obj = _resolve(doc, op.get("obj"), aliases)
    name = op.get("name")
    if not isinstance(name, str) or name not in obj.PropertiesList:
        raise _invalid("remove_property: %s has no property %r" % (obj.Name, name), "name")
    if not properties._is_dynamic(obj, name):
        raise OperationError("not_dynamic", 409, "remove_property: %s is built in" % name, name)
    obj.removeProperty(name)
    return {"op": "remove_property", "name": obj.Name, "prop": name}


_HANDLERS = {
    "create": _op_create,
    "delete": _op_delete,
    "patch": _op_patch,
    "set_expression": _op_set_expression,
    "set_cells": _op_set_cells,
    "add_property": _op_add_property,
    "remove_property": _op_remove_property,
}


# -- The batch ----------------------------------------------------------


def _error_names(doc):
    return {entry["name"] for entry in writes.state_errors(list(doc.Objects))}


def _as_operation_error(exc, index, op):
    """Every cause becomes a response that says WHICH operation failed."""
    where = {"failedOp": index, "op": op.get("op") if isinstance(op, dict) else None}
    if isinstance(exc, BridgeError):
        detail = dict(where, detail=exc.detail)
        # field/reason additionally at the top level: the same shape as for
        # PATCH, so the UI can translate the message the same way.
        if isinstance(exc.detail, dict):
            for key in ("field", "reason"):
                if key in exc.detail:
                    detail[key] = exc.detail[key]
        return OperationError(exc.code, exc.http_status, exc.message, detail)
    if isinstance(exc, (ArithmeticError, ValueError, TypeError)) or type(exc).__name__ == "ParserError":
        # FreeCAD itself rejected the value -- "rejected", as with PATCH.
        detail = dict(where, reason="rejected", error=str(exc))
        return OperationError("invalid_value", 400, "%s: %s" % (where["op"], exc), detail)
    return OperationError("operation_failed", 500, "%s failed: %s" % (where["op"], exc), where)


@main_thread_only
def run(doc_name, ops, name=None, request_id=None, strict=True):
    """Run a batch -- one undo step, all or nothing.

    ``strict``: if the batch makes an object invalid (such as an expression
    on an unknown alias), everything is rolled back (409
    recompute_failed). Objects that were already broken before do not count.
    """
    replay = writes.cached_response(request_id)
    if replay is not None:
        return replay

    _validate(ops)
    if name is not None and not isinstance(name, str):
        raise _invalid("name must be text")

    doc = documents.get_document(doc_name)
    documents.ensure_undo_enabled(doc)
    if doc.UndoMode == 0:
        raise writes.UndoDisabled("Undo is disabled for %r" % doc.Name)
    if writes.active_transaction_id() is not None:
        raise CadBusyError("A transaction is currently open in FreeCAD", "transaction_open")

    _precheck_revisions(doc, ops)
    errors_before = _error_names(doc)

    state = bridge_state.get_state()
    state.active_request_id = request_id or "anonymous"
    aliases = {}
    results = []
    tid = FreeCAD.setActiveTransaction(name or "Platform: %d operation(s)" % len(ops))
    index, op = -1, None
    try:
        try:
            for index, op in enumerate(ops):
                results.append(_HANDLERS[op["op"]](doc, op, aliases))
            index, op = None, None
            changed = bool(doc.HasPendingTransaction)
            recomputed = doc.recompute() if changed else 0
            new_errors = [e for e in writes.state_errors(list(doc.Objects)) if e["name"] not in errors_before]
            if strict and new_errors:
                raise RecomputeFailed(
                    "%d object(s) are broken after the transaction -- everything rolled back" % len(new_errors),
                    {"errors": new_errors},
                )
        except Exception as exc:
            ours = writes.active_transaction_id() == tid
            if ours:
                FreeCAD.closeActiveTransaction(True)
                try:
                    doc.recompute()
                except Exception:
                    pass
            if index is None:
                if isinstance(exc, BridgeError):
                    raise
                raise OperationError("operation_failed", 500, "Recompute failed: %s" % exc)
            raise _as_operation_error(exc, index, op)

        atomic = writes.active_transaction_id() == tid
        if atomic:
            FreeCAD.closeActiveTransaction()
        else:
            log.warn("Transaction %s was taken over by a FreeCAD command" % tid, request_id)
    finally:
        state.active_request_id = None

    observer.flush_now("write")

    deleted = {r["name"] for r in results if r["op"] == "delete"}
    touched = sorted({r["name"] for r in results} - deleted)
    response = {
        "status": "done",
        "atomic": atomic,
        "changed": changed,
        "created": aliases,
        "results": results,
        "recomputed": recomputed,
        "errors": writes.state_errors(list(doc.Objects)),
        "revs": {obj_name: revisions.current(doc.Name, obj_name) for obj_name in touched},
    }
    writes.remember_response(request_id, response)
    return response


# -- Reading spreadsheets -----------------------------------------------


class InvalidRange(BridgeError):
    code = "invalid_range"
    http_status = 400


MAX_CELLS = 5000


def _column_number(letters):
    number = 0
    for char in letters:
        number = number * 26 + (ord(char) - ord("A") + 1)
    return number


def _split_cell(cell):
    match = re.match(r"^([A-Z]{1,3})([0-9]{1,6})$", cell)
    if not match:
        raise InvalidRange("Invalid cell %r" % cell)
    return _column_number(match.group(1)), int(match.group(2))


def parse_range(text):
    """'A1:D100' -> ((col1, row1), (col2, row2)); None = all used cells."""
    if not text:
        return None
    parts = text.upper().split(":")
    if len(parts) == 1:
        parts = parts * 2
    if len(parts) != 2:
        raise InvalidRange("Invalid range %r (expected A1:D100)" % text)
    (c1, r1), (c2, r2) = _split_cell(parts[0]), _split_cell(parts[1])
    return (min(c1, c2), min(r1, r2)), (max(c1, c2), max(r1, r2))


def _encode_cell_value(value):
    if isinstance(value, FreeCAD.Units.Quantity):
        return properties._encode_quantity(value)
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return types.unsupported(type(value).__name__, "cell value not representable")


@main_thread_only
def read_cells(doc_name, sheet_name, cell_range=None):
    """Used cells of a spreadsheet -- content (formula/text), value and alias.

    Iteration goes over getUsedCells(), never over the whole range: a
    range A1:ZZZ999999 would otherwise be a pass over hundreds of millions.
    """
    doc = documents.get_document(doc_name)
    sheet = _sheet(doc, sheet_name, {})
    bounds = parse_range(cell_range)

    cells = {}
    truncated = False
    for cell in sheet.getUsedCells():
        if bounds is not None:
            column, row = _split_cell(cell)
            (c1, r1), (c2, r2) = bounds
            if not (c1 <= column <= c2 and r1 <= row <= r2):
                continue
        if len(cells) >= MAX_CELLS:
            truncated = True
            break
        try:
            value = _encode_cell_value(sheet.get(cell))
        except Exception:
            value = None
        cells[cell] = {
            "content": sheet.getContents(cell),
            "value": value,
            "alias": sheet.getAlias(cell) or None,
        }
    return {"doc": doc.Name, "sheet": sheet.Name, "cells": cells, "truncated": truncated,
            "rev": revisions.current(doc.Name, sheet.Name)}
