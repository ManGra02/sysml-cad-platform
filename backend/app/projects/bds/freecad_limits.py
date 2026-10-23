"""Writing requirement limits into a FreeCAD document through the bridge (``ctx.cad``).

The one place the BDS writes into CAD. What gets written (which limit, under which
alias) is limits.py's; this is HOW it lands in FreeCAD: a spreadsheet the sync owns,
marked in A1, its rows tagged in column C -- a designer's sheet is never touched.
"""

from __future__ import annotations

import math
import re

from app.projects.base import CadError
from app.projects.bds.adapters import LimitChange, Unsupported
from app.projects.bds.freecad_snapshot import SHEET_TYPE, decode_quantity
from app.projects.bds.units import ureg

#: Cell A1 of a sheet the sync owns. A sheet of that name without it is a designer's
#: and is never written.
MARKER = "managed by sysml-cad-platform BDS -- do not edit"
OWNER = "bds"

_CELL = re.compile(r"([A-Z]+)(\d+)")

_FREECAD_BASE = (("[length]", "mm"), ("[mass]", "kg"), ("[time]", "s"), ("[current]", "A"),
                 ("[temperature]", "K"), ("[substance]", "mol"), ("[luminosity]", "cd"))
_ANGLE_UNITS = {"degree", "radian", "arcminute", "arcsecond", "turn"}


def freecad_text(quantity):
    """A quantity as FreeCAD expression text in its internal units: ``100 mm``,
    ``2.7e-06 kg/mm^3``, ``45 deg``."""
    if str(quantity.units) in _ANGLE_UNITS:
        return "%r deg" % float(quantity.to(ureg.degree).magnitude)
    dims = quantity.dimensionality
    unknown = set(dims) - {key for key, _ in _FREECAD_BASE}
    if unknown:
        raise Unsupported("%s: dimension %s has no FreeCAD unit" % (format(quantity, "~P"), sorted(unknown)))
    base = ureg.dimensionless
    numerator, denominator = [], []
    for key, symbol in _FREECAD_BASE:
        exponent = dims.get(key, 0)
        if not exponent:
            continue
        if exponent != int(exponent):
            raise Unsupported("%s: fractional dimension" % format(quantity, "~P"))
        exponent = int(exponent)
        base = base * ureg.parse_units(symbol) ** exponent
        text = symbol if abs(exponent) == 1 else "%s^%d" % (symbol, abs(exponent))
        (numerator if exponent > 0 else denominator).append(text)
    value = float(quantity.to(base).magnitude)
    if not numerator and not denominator:
        return repr(value)
    unit = "*".join(numerator) or "1"
    if denominator:
        unit += "/" + ("/".join(denominator))
    return "%r %s" % (value, unit)


async def write_limits(cad, document, sheet, values, apply=False):
    """Write requirement limits into the sheet the sync owns.

    Layout from row 2 down: A the alias as text, B the value (aliased), C "bds".
    A sheet with that label but without the marker in A1 is a designer's and is
    refused. Only cells in rows whose C reads "bds" are ever changed. With
    ``apply=False`` nothing is written and the result is the diff. All changes go
    in ONE bridge transaction -- one undo step in FreeCAD.
    """
    if "#" in document:
        raise Unsupported("limits are written into a document, not into %r" % document)
    try:
        tree = await cad.tree(document)
    except CadError as exc:
        raise Unsupported("FreeCAD document %r cannot be written: %s" % (document, exc.message or exc.code)) from None
    sheets = [name for name, node in (tree.get("nodes") or {}).items()
              if node.get("typeId") == SHEET_TYPE and (node.get("label") or name) == sheet]
    if len(sheets) > 1:
        raise Unsupported("%s has %d spreadsheets labelled %r" % (document, len(sheets), sheet))

    rows, used = {}, 1
    sheet_name = sheets[0] if sheets else None
    if sheet_name is not None:
        cells = (await cad.cells(document, sheet_name)).get("cells") or {}
        if (cells.get("A1") or {}).get("content") != MARKER:
            raise Unsupported("spreadsheet %r in %s is not the sync's (no marker in A1) -- rename it, "
                              "or set another limits_sheet for this workspace" % (sheet, document))
        for cell in cells:
            match = _CELL.fullmatch(cell)
            if match:
                used = max(used, int(match.group(2)))
        for cell, data in cells.items():
            match = _CELL.fullmatch(cell)
            if not match or match.group(1) != "B" or not data.get("alias"):
                continue
            row = int(match.group(2))
            if (cells.get("C%d" % row) or {}).get("content") != OWNER:
                continue
            try:
                old = decode_quantity(data.get("value"))
            except Unsupported:
                old = None
            rows[data["alias"]] = (row, old)

    changes, cell_updates, alias_updates = [], {}, {}
    next_row = max(used, 1) + 1
    for alias, new in sorted(values.items()):
        text = freecad_text(new)
        if alias in rows:
            row, old = rows[alias]
            if old is not None and _same(old, new):
                continue
        else:
            row, old = next_row, None
            next_row += 1
            cell_updates["A%d" % row] = alias
            cell_updates["C%d" % row] = OWNER
            alias_updates["B%d" % row] = alias
        cell_updates["B%d" % row] = "=" + text
        changes.append(LimitChange(alias=alias, old=old, new=new))

    if apply and changes:
        try:
            async with cad.transaction(document, "BDS: SysML limits") as tx:
                target = sheet_name
                if target is None:
                    target = tx.create(SHEET_TYPE, name=sheet, label=sheet)
                    cell_updates["A1"] = MARKER
                tx.set_cells(target, cells=cell_updates, aliases=alias_updates or None)
        except CadError as exc:
            raise Unsupported("FreeCAD refused the limits: %s (%s)" % (exc.message or exc.code, exc.code)) from None
    return changes


def _same(old, new):
    if old.dimensionality != new.dimensionality:
        return False
    a, b = float(old.to(new.units).magnitude), float(new.magnitude)
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
