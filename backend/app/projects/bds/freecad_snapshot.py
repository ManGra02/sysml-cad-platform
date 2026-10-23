"""A snapshot of the FreeCAD documents, read through the platform's bridge (``ctx.cad``).

Replaces the PoC's own headless FreeCAD worker: the documents are the ones open in
the user's FreeCAD, read over the bridge's HTTP API. Everything is read ONCE per run
(``FreeCADSnapshot.load``) -- tree, properties, geometry of the listed objects, spreadsheet
aliases -- so every measurement afterwards is a lookup in one consistent snapshot, and
the verification logic above stays synchronous.

ADDRESSING (a mapping entry's ``cad_object``)

    Gearbox#Body001     one object of document "Gearbox", by its Name (stable; the
                        Label is only shown). A Label is accepted when no Name
                        matches, and refused when it is ambiguous.
    Gearbox             the document's one root object, if it has exactly one

WHICH OBJECTS ARE LISTED: those a requirement can be about -- PartDesign bodies,
App::Part / assembly containers, and any other shape that no other feature consumes
(the operands of a boolean, a Body's features and sketches are not listed).

WHAT IS REFUSED: an object FreeCAD marks invalid or touched (a stale shape is never
measured -- recompute in FreeCAD first), a document that is not open, and a bridge
that is not running. Every one of them is ``Unsupported``, i.e. a gap in the run.

Writing (the requirement limits) is not a snapshot's job: see freecad_limits.
"""

from __future__ import annotations

import hashlib
import math

from app import config
from app.projects.base import CadError, seg
from app.projects.bds.adapters import (
    METHODS,
    NEEDS_PARAMETERS,
    CadTarget,
    Material,
    Unsupported,
    check_args,
    check_density,
)
from app.projects.bds.units import Q, ureg
from app.projects.bds.workspace import DEFAULT_LIMITS_SHEET

CONTAINER_TYPES = {"App::Part", "Assembly::AssemblyObject"}
#: Objects whose dependencies are not "consumed" by them: containers group, links point.
NON_CONSUMING_TYPES = CONTAINER_TYPES | {"App::DocumentObjectGroup", "App::Link", "App::LinkGroup"}
SHEET_TYPE = "Spreadsheet::Sheet"
SKIPPED_TYPE_PREFIXES = ("Sketcher::", "Spreadsheet::", "App::VarSet", "App::MaterialObject")

_SAME_CYLINDER_MM = 1e-4
_AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


# --------------------------------------------------------------------------
# Quantities on the wire (cad_contract.types.quantity)
# --------------------------------------------------------------------------

_SYMBOLS = {"°": "degree", "deg": "degree"}


def decode_quantity(data):
    """``{"kind": "quantity", "value": 100.0, "unit": "mm"}`` -> 100 mm; a plain number
    is dimensionless. ``value`` is FreeCAD's internal value, ``unit`` its internal unit."""
    if isinstance(data, bool):
        raise Unsupported("a boolean is not a quantity")
    if isinstance(data, (int, float)):
        if not math.isfinite(data):
            raise Unsupported("quantity %r is not finite" % data)
        return Q(float(data), ureg.dimensionless)
    if not isinstance(data, dict) or data.get("kind") != "quantity":
        raise Unsupported("not a quantity: %r" % (data,))
    value = data.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Unsupported("quantity value %r is not a finite number" % (value,))
    symbol = (data.get("unit") or "").strip()
    if not symbol:
        return Q(float(value), ureg.dimensionless)
    symbol = _SYMBOLS.get(symbol, symbol).replace("^", "**")
    try:
        return Q(float(value), ureg.parse_units(symbol))
    except Exception as exc:
        raise Unsupported("FreeCAD unit %r is not understood (%s)" % (data.get("unit"), exc)) from None


# --------------------------------------------------------------------------
# One document, as read from the bridge
# --------------------------------------------------------------------------

class _Object:
    def __init__(self, name, label, type_id, rev, state):
        self.name = name
        self.label = label
        self.type = type_id
        self.rev = rev
        self.state = list(state or [])
        self.parent = None          # Name of the nearest listed container
        self.depth = 0
        self.geometry = None
        self.children = []
        self.parameters = {}        # quantity properties of this object and its features

    @property
    def has_shape(self):
        return bool(self.geometry) and not self.geometry.get("null")

    @property
    def error(self):
        if "Invalid" in self.state or "Error" in self.state:
            return "FreeCAD marks it invalid -- fix and recompute it in FreeCAD"
        if "Touched" in self.state:
            return "it changed since the last recompute -- recompute in FreeCAD first"
        return None

    @property
    def material(self):
        data = (self.geometry or {}).get("material")
        if not data or data.get("default"):
            return None
        density = data.get("density")
        try:
            density = decode_quantity(density) if density else None
        except Unsupported:
            density = None
        if density is not None and (density.dimensionality != (ureg.kg / ureg.m**3).dimensionality
                                    or not density.magnitude > 0):
            density = None
        return Material(name=data.get("name") or "unnamed", density=density)


class _Document:
    def __init__(self, name):
        self.name = name
        self.objects = {}           # Name -> _Object, listed objects only
        self.parameters = {}        # document-wide: spreadsheet aliases, VarSets, loose features
        self.sheets = {}            # label -> Name
        self.revs = {}
        self.error = None

    @property
    def roots(self):
        return [o for o in self.objects.values() if o.parent is None]

    def parameters_of(self, obj):
        return {**self.parameters, **obj.parameters}

    def reference(self, obj):
        roots = self.roots
        if len(roots) == 1 and roots[0] is obj:
            return self.name
        return "%s#%s" % (self.name, obj.name)

    def resolve(self, key):
        if key is None:
            roots = self.roots
            if len(roots) != 1:
                raise Unsupported("document %s has %d root objects (%s); address one as '%s#<Name>'"
                                  % (self.name, len(roots), ", ".join(sorted(o.name for o in roots)) or "none",
                                     self.name))
            return roots[0]
        if key in self.objects:
            return self.objects[key]
        by_label = [o for o in self.objects.values() if o.label == key]
        if len(by_label) == 1:
            return by_label[0]
        if len(by_label) > 1:
            raise Unsupported("%s: label %r is ambiguous (%s) -- address it by Name"
                              % (self.name, key, ", ".join(o.name for o in by_label)))
        raise Unsupported("%s has no measurable object %r. Available: %s"
                          % (self.name, key, ", ".join("%s (%s)" % (o.name, o.label)
                                                      for o in self.objects.values()) or "none"))


def _parents(nodes):
    parents = {}
    for name, node in nodes.items():
        for child in node.get("children") or []:
            parents.setdefault(child, []).append(name)
    return parents


async def _read_document(cad, doc, limits_sheet):
    document = _Document(doc)
    tree = await cad.tree(doc)
    nodes = tree.get("nodes") or {}
    listing = await cad.get("/documents/%s/objects" % seg(doc))
    described = {o["name"]: o for o in listing.get("objects") or []}

    consumed = set()
    for node in nodes.values():
        if node.get("typeId") in NON_CONSUMING_TYPES:
            continue
        consumed.update(node.get("deps") or [])

    def has_shape_property(name):
        return any(p.get("name") == "Shape" for p in (described.get(name) or {}).get("properties") or [])

    for name, node in nodes.items():
        type_id = node.get("typeId") or ""
        document.revs[name] = node.get("rev")
        if type_id == SHEET_TYPE:
            document.sheets.setdefault(node.get("label") or name, name)
        if node.get("internal") or type_id.startswith(SKIPPED_TYPE_PREFIXES):
            continue
        listed = type_id in CONTAINER_TYPES or (has_shape_property(name) and name not in consumed)
        if listed:
            document.objects[name] = _Object(name, node.get("label") or name, type_id,
                                             node.get("rev"), node.get("state"))

    if document.objects:
        names = ",".join(document.objects)
        geometry = await cad.get("/documents/%s/objects" % seg(doc), names=names,
                                 include="geometry", fields="Label", timeout=config.GEOMETRY_TIMEOUT_S)
        for item in geometry.get("objects") or []:
            if item.get("name") in document.objects:
                document.objects[item["name"]].geometry = item.get("geometry")
        # Without a shape there is nothing to measure (an empty Body, a broken link).
        document.objects = {n: o for n, o in document.objects.items()
                            if o.has_shape or o.type in CONTAINER_TYPES}

    # Nearest listed container above each listed object (the tree is a DAG; the first
    # path that reaches a container wins).
    parents = _parents(nodes)
    for obj in document.objects.values():
        seen, frontier = {obj.name}, [obj.name]
        while frontier and obj.parent is None:
            above = [p for name in frontier for p in parents.get(name, []) if p not in seen]
            seen.update(above)
            obj.parent = next((p for p in above if p in document.objects
                               and document.objects[p].type in CONTAINER_TYPES), None)
            frontier = above
    for obj in document.objects.values():
        if obj.parent is not None:
            document.objects[obj.parent].children.append(obj.name)
    # Depth counts listed containers only.
    for obj in document.objects.values():
        depth, parent = 0, obj.parent
        while parent is not None and depth < 32:
            depth += 1
            parent = document.objects[parent].parent
        obj.depth = depth

    await _read_parameters(cad, document, nodes, described, parents, limits_sheet)
    return document


def _owner(name, document, parents):
    """The listed object a feature belongs to (a Pad -> its Body), or None."""
    seen, frontier = {name}, [name]
    while frontier:
        if any(n in document.objects for n in frontier):
            return next(n for n in frontier if n in document.objects)
        frontier = [p for n in frontier for p in parents.get(n, []) if p not in seen]
        seen.update(frontier)
    return None


async def _read_parameters(cad, document, nodes, described, parents, limits_sheet):
    """Named values: spreadsheet aliases (``Params.Length``, document-wide) and quantity
    properties (``Pad.Length``) -- those of a feature belong to the listed object that
    owns it (a Pad to its Body), so a proposer never sees the housing's Pad as a
    parameter of the cover. VarSets and loose features are document-wide. The sync's own
    sheet is left out (its values are limits, not parameters), and so are exact zeros:
    an unused Offset or TaperAngle of 0 says nothing about a part."""
    for label, sheet in sorted(document.sheets.items()):
        if label == limits_sheet:
            continue
        cells = (await cad.cells(document.name, sheet)).get("cells") or {}
        for cell in cells.values():
            alias = cell.get("alias")
            if not alias:
                continue
            try:
                document.parameters["%s.%s" % (label, alias)] = decode_quantity(cell.get("value"))
            except Unsupported:
                continue          # text, or a unit pint does not know

    for name, node in nodes.items():
        type_id = node.get("typeId") or ""
        if node.get("internal") or type_id.startswith(("Spreadsheet::", "Sketcher::")):
            continue
        label = node.get("label") or name
        for prop in (described.get(name) or {}).get("properties") or []:
            value = prop.get("value")
            if prop.get("status") != "encoded" or not isinstance(value, dict) or value.get("kind") != "quantity":
                continue
            try:
                quantity = decode_quantity(value)
            except Unsupported:
                continue
            if quantity.magnitude == 0:
                continue
            owner = _owner(name, document, parents)
            target = document.objects[owner].parameters if owner else document.parameters
            target.setdefault("%s.%s" % (label, prop.get("name")), quantity)


# --------------------------------------------------------------------------
# The adapter
# --------------------------------------------------------------------------

def _bbox_size(axis="X"): ...
def _volume(): ...
def _face_count(): ...
def _cylinder_radius(kind=None, axis=None): ...
def _mass(density_g_per_cm3=None): ...
def _parameter(name): ...


#: Signatures for check_args: a typo in ``args:`` is one gap, caught before measuring.
_SIGNATURES = {"bbox_size": _bbox_size, "volume": _volume, "face_count": _face_count,
               "cylinder_radius": _cylinder_radius, "mass": _mass, "parameter": _parameter}


class FreeCADSnapshot:
    name = "freecad"

    def __init__(self, cad, limits_sheet=DEFAULT_LIMITS_SHEET):
        self._cad = cad
        self._limits_sheet = limits_sheet
        self._documents = {}

    @classmethod
    async def load(cls, cad, documents, limits_sheet=DEFAULT_LIMITS_SHEET):
        """Read every named document once. One that cannot be read is kept with the
        reason, so its objects become gaps instead of failing the run."""
        adapter = cls(cad, limits_sheet)
        for doc in dict.fromkeys(d for d in documents if d):
            await adapter._load(doc)
        return adapter

    async def _load(self, doc):
        try:
            self._documents[doc] = await _read_document(self._cad, doc, self._limits_sheet)
        except CadError as exc:
            document = _Document(doc)
            if exc.code == "doc_not_open":
                document.error = "FreeCAD document %r is not open -- open it in FreeCAD" % doc
            else:
                document.error = "FreeCAD bridge: %s (%s)" % (exc.message or exc.code, exc.code)
            self._documents[doc] = document

    @property
    def documents(self):
        return list(self._documents)

    def _document(self, doc):
        document = self._documents.get(doc)
        if document is None:
            raise Unsupported("FreeCAD document %r was not loaded for this run" % doc)
        if document.error:
            raise Unsupported(document.error)
        return document

    def _object(self, reference):
        doc, _, key = reference.partition("#")
        document = self._document(doc)
        return document, document.resolve(key or None)

    # -- CadAdapter ---------------------------------------------------------

    def state_id(self):
        """Digest over the revisions of every object read: two runs with the same id
        measured the same design state."""
        digest = hashlib.sha256()
        for doc in sorted(self._documents):
            digest.update(doc.encode())
            for name, rev in sorted(self._documents[doc].revs.items()):
                digest.update(("%s=%s;" % (name, rev)).encode())
        return digest.hexdigest()[:16]

    def objects(self):
        return [document.reference(obj) for document in self._documents.values() if not document.error
                for obj in document.objects.values()]

    def parameter(self, reference, name):
        document, obj = self._object(reference)
        return document.parameters_of(obj).get(name)

    def material(self, reference):
        _, obj = self._object(reference)
        return obj.material

    def measure(self, reference, method, args=None):
        if method not in METHODS:
            raise Unsupported("unknown measurement method: %s" % method)
        args = dict(args or {})
        check_args(method, _SIGNATURES[method], **args)
        document, obj = self._object(reference)

        if method == "parameter":
            available = document.parameters_of(obj)
            value = available.get(args["name"])
            if value is None:
                raise Unsupported("%s has no parameter %r%s" % (
                    reference, args["name"], ". Available: %s" % ", ".join(sorted(available)) if available else ""))
            return value

        if obj.error:
            raise Unsupported("%s#%s (%s): %s" % (document.name, obj.name, obj.label, obj.error))
        if not obj.has_shape:
            raise Unsupported("%s#%s carries no shape" % (document.name, obj.name))
        geometry = obj.geometry

        if method == "bbox_size":
            axis = str(args.get("axis", "X")).upper()
            if axis not in ("X", "Y", "Z"):
                raise Unsupported("bbox_size: axis must be X, Y or Z, not %r" % (args.get("axis"),))
            box = geometry.get("tightBoundBox") or geometry.get("boundBox")
            if not box:
                raise Unsupported("%s#%s: FreeCAD gave no bounding box" % (document.name, obj.name))
            return box["lengths"]["XYZ".index(axis)] * ureg.mm
        if method == "volume":
            if geometry.get("volume") is None:
                raise Unsupported("%s#%s: FreeCAD gave no volume" % (document.name, obj.name))
            return geometry["volume"] * ureg.mm**3
        if method == "face_count":
            faces = (geometry.get("counts") or {}).get("faces")
            if faces is None:
                raise Unsupported("%s#%s: FreeCAD gave no face count" % (document.name, obj.name))
            return faces * ureg.dimensionless
        if method == "cylinder_radius":
            return _cylinder_radius_of(geometry, args.get("kind"), args.get("axis"))
        override = args.get("density_g_per_cm3")
        if override is not None:
            density = check_density(override) * ureg.g / ureg.cm**3
            return (_volume_of(document, obj) * density).to(ureg.kg)
        return _mass_of(document, obj)

    def catalog(self):
        """One target per listed object of each document. A document that cannot be
        read is ONE target without methods and the reason in its note -- listed, not
        dropped, so a closed document reads as exactly that."""
        out = []
        for doc, document in self._documents.items():
            if document.error:
                out.append(CadTarget(adapter=self.name, reference=doc, kind="part", name=doc, methods=(),
                                     note="not readable: %s" % document.error))
                continue
            labels = {}
            for obj in document.objects.values():
                labels.setdefault(obj.label, []).append(obj)
            for obj in document.objects.values():
                material = obj.material
                methods = () if obj.error else tuple(
                    m for m in METHODS
                    if (m != "mass" or _has_mass(document, obj))
                    and (m not in NEEDS_PARAMETERS or document.parameters_of(obj)))
                notes = []
                if obj.error:
                    notes.append("not measurable: %s" % obj.error)
                notes.append("material %s" % material.name if material is not None
                             else "no material in the document")
                if obj.parent is not None:
                    notes.append("component of %s" % document.objects[obj.parent].label)
                if len(labels[obj.label]) > 1:
                    notes.append("label shared by %d objects" % len(labels[obj.label]))
                parent = document.objects.get(obj.parent) if obj.parent else None
                out.append(CadTarget(
                    adapter=self.name,
                    reference=document.reference(obj),
                    kind="assembly" if obj.children else "part",
                    name=obj.label,
                    methods=methods,
                    parameters=document.parameters_of(obj),
                    note=", ".join(notes),
                    depth=obj.depth,
                    container=document.reference(parent) if parent is not None else "",
                ))
        return out

    async def write_limits(self, document, sheet, values, apply=False):
        """Written by freecad_limits; here so the adapter pool reaches it. What this run
        read of a document it changed is stale afterwards."""
        from app.projects.bds.freecad_limits import write_limits   # it imports this module

        changes = await write_limits(self._cad, document, sheet, values, apply=apply)
        if apply and changes:
            self._documents.pop(document, None)
        return changes


def _volume_of(document, obj):
    volume = (obj.geometry or {}).get("volume")
    if volume is None:
        raise Unsupported("%s#%s: FreeCAD gave no volume" % (document.name, obj.name))
    return volume * ureg.mm**3


def _mass_of(document, obj):
    """Volume times the density of the object's own material. A container without
    one weighs what its parts weigh, each with its own material -- a part without a
    density is a gap, never a guess."""
    if obj.error:
        raise Unsupported("%s#%s (%s): %s" % (document.name, obj.name, obj.label, obj.error))
    material = obj.material
    if material is not None and material.density is not None:
        return (_volume_of(document, obj) * material.density).to(ureg.kg)
    if obj.type in CONTAINER_TYPES and obj.children:
        total = 0 * ureg.kg
        for child in obj.children:
            total = total + _mass_of(document, document.objects[child])
        return total
    raise Unsupported("%s#%s (%s) has no material with a density -- assign one in FreeCAD"
                      % (document.name, obj.name, obj.label))


def _has_mass(document, obj):
    try:
        _mass_of(document, obj)
    except Unsupported:
        return False
    return True


def _cylinder_radius_of(geometry, kind=None, axis=None):
    """Radius of the ONE cylindrical feature. Faces are grouped into features by kind,
    radius and axis LINE (a bore split by a seam is one feature); ``kind`` and ``axis``
    narrow. None left is a gap; several is an error, never a choice -- the first one
    would be a plausible number from the wrong feature."""
    if kind is not None and kind not in ("hole", "boss"):
        raise Unsupported("cylinder_radius: kind must be hole or boss, not %r" % (kind,))
    direction = None
    if axis is not None:
        direction = _AXES.get(str(axis).upper())
        if direction is None:
            raise Unsupported("cylinder_radius: axis must be X, Y or Z, not %r" % (axis,))
    if geometry.get("cylindersTruncated"):
        raise Unsupported("cylinder_radius: too many cylindrical faces to tell one feature apart")
    if "cylinders" not in geometry:
        raise Unsupported("cylinder_radius: this FreeCAD bridge reports no cylinders (contract < 0.7.0)")

    features = []
    for face in geometry.get("cylinders") or []:
        along = _unit(face["axis"])
        if kind is not None and face["kind"] != kind:
            continue
        if direction is not None and abs(abs(_dot(along, direction)) - 1) > 1e-9:
            continue
        feature = {"radius": face["radius"], "origin": face["center"], "along": along, "kind": face["kind"]}
        if not any(_same_cylinder(feature, known) for known in features):
            features.append(feature)

    narrowed = ", ".join("%s=%s" % (k, v) for k, v in (("kind", kind), ("axis", axis)) if v)
    if not features:
        raise Unsupported("cylinder_radius: no cylindrical face" + (" with %s" % narrowed if narrowed else ""))
    if len(features) > 1:
        found = ", ".join("%s r=%.4g mm along (%.3g, %.3g, %.3g)" % ((f["kind"], f["radius"]) + tuple(f["along"]))
                          for f in features)
        raise Unsupported("cylinder_radius: %d cylindrical features%s (%s) -- narrow it with kind or axis"
                          % (len(features), " with %s" % narrowed if narrowed else "", found))
    return features[0]["radius"] * ureg.mm


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _unit(v):
    length = math.sqrt(_dot(v, v)) or 1.0
    return [x / length for x in v]


def _same_cylinder(a, b):
    """Same kind, same radius, and the same axis LINE -- parallel is not enough."""
    if a["kind"] != b["kind"] or abs(a["radius"] - b["radius"]) > _SAME_CYLINDER_MM:
        return False
    if abs(abs(_dot(a["along"], b["along"])) - 1) > 1e-9:
        return False
    offset = [y - x for x, y in zip(a["origin"], b["origin"])]
    along = _dot(offset, a["along"])
    off_line = [o - along * d for o, d in zip(offset, a["along"])]
    return math.sqrt(_dot(off_line, off_line)) <= _SAME_CYLINDER_MM
