"""CAD side backed by STEP files (ISO 10303, AP203/AP214/AP242).

This is the adapter that makes the project usable on a model it did not write
itself: point it at a file any CAD system exported and it measures. FreeCAD,
CATIA, Creo, NX, SolidWorks and Onshape all write STEP, and OCCT reads it --
no extra dependency, because build123d already brings the kernel.

WHY XCAF AND NOT build123d.import_step
--------------------------------------
`import_step` mangles node names: it maps " .()" to "_", so a CATIA part called
"Housing (rev A)" arrives as "Housing__rev_A_". This project's core convention
is stable identity through names, so a lossy name is the wrong foundation.
`import_step` also surfaces colours but not materials. Driving XCAF
(STEPCAFControl_Reader) directly costs about sixty lines and keeps the names
the CAD system actually wrote.

WHAT STEP CANNOT DO
-------------------
A STEP file is baked geometry. There are no named parameters -- `parameter()`
returns None, always, and honestly. There is no parametric write-back either.
Both are what the FreeCAD adapter is for; this adapter reads.

ADDRESSING
----------
    cad/step/gearbox.step#Housing    one node of an assembly, by name
    cad/step/shaft.step              the whole file

Paths resolve against the repository root. A name matching more than one node
is an error, never a choice -- picking the first would be the same class of bug
as substituting a value.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from build123d import Compound, Shape, Shell, Solid
from build123d.topology.shape_core import downcast, shapetype

from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_ShapeEnum
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from ..units import Q, ureg
from . import METHODS, CadTarget, Material, Unsupported
from . import measurements as mm

ROOT = Path(__file__).resolve().parents[3]

_METHODS = {"bbox_size", "volume", "mass", "face_count"}

#: Which build123d wrapper fits which OCCT shape type. Explicit rather than
#: build123d's internal shape_LUT, whose values are class *names*, not classes.
#: Only the volumetric types are listed -- a loose face or edge is not
#: something this system should be measuring a part against.
_WRAPPERS = {
    TopAbs_ShapeEnum.TopAbs_COMPOUND: Compound,
    TopAbs_ShapeEnum.TopAbs_COMPSOLID: Compound,
    TopAbs_ShapeEnum.TopAbs_SOLID: Solid,
    TopAbs_ShapeEnum.TopAbs_SHELL: Shell,
}


class _Node:
    """One addressable shape inside a STEP file."""

    __slots__ = ("name", "path", "label", "is_assembly", "children")

    def __init__(self, name: str, path: str, label: TDF_Label, is_assembly: bool):
        self.name = name
        self.path = path              # e.g. "Gearbox/Housing", for reporting
        self.label = label
        self.is_assembly = is_assembly
        self.children: list["_Node"] = []


class StepAdapter:
    """Addresses STEP files by path, with an optional node name after '#'."""

    name = "step"

    def __init__(self, root: Path | None = None):
        self._root = Path(root) if root else ROOT
        self._files: dict[Path, dict] = {}
        self._loaded: list[str] = []

    # -- reference parsing --------------------------------------------------

    def _resolve(self, obj: str) -> tuple[Path, str | None]:
        ref, _, node = obj.partition("#")
        path = Path(ref)
        if not path.is_absolute():
            path = self._root / path
        return path, (node or None)

    # -- reading ------------------------------------------------------------

    def _read(self, path: Path) -> dict:
        """Read a STEP file through XCAF once, and index its nodes by name."""
        if path in self._files:
            return self._files[path]
        if not path.is_file():
            raise Unsupported(f"no STEP file at {path}")

        # The unit conversion target is a PROCESS-GLOBAL OCCT static. Set it on
        # every read rather than trusting whatever ran before us: a file authored
        # in inches must come back in millimetres, and a silent factor of 25.4 is
        # the worst possible failure for a verification tool.
        Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")

        doc = TDocStd_Document(TCollection_ExtendedString("step"))
        reader = STEPCAFControl_Reader()
        reader.SetNameMode(True)
        reader.SetColorMode(True)
        reader.SetMatMode(True)

        if reader.ReadFile(str(path)).name != "IFSelect_RetDone":
            raise Unsupported(f"{path.name}: STEP file could not be read")
        if not reader.Transfer(doc):
            raise Unsupported(f"{path.name}: STEP file carries no transferable shape")

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        by_name: dict[str, list[_Node]] = {}
        roots: list[_Node] = []

        free = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free)
        for i in range(1, free.Length() + 1):
            roots.append(self._index(shape_tool, free.Value(i), "", by_name))

        entry = {
            "doc": doc,
            "shape_tool": shape_tool,
            "by_name": by_name,
            "roots": roots,
            "digest": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
        }
        self._files[path] = entry
        return entry

    def _index(self, shape_tool, label, prefix: str, by_name: dict) -> _Node:
        """Walk the assembly tree, collecting every named node."""
        name = self._label_name(shape_tool, label) or "unnamed"
        path = f"{prefix}/{name}" if prefix else name
        is_assembly = shape_tool.IsAssembly_s(label)
        node = _Node(name, path, label, is_assembly)
        by_name.setdefault(name, []).append(node)

        children = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, children)
        for i in range(1, children.Length() + 1):
            node.children.append(
                self._index(shape_tool, children.Value(i), path, by_name)
            )
        return node

    @staticmethod
    def _label_name(shape_tool, label) -> str | None:
        """The name the CAD system wrote, unmangled.

        A component label is a reference; its own name is the instance name and
        the product name sits on the label it refers to. Prefer the instance
        name, fall back to the product.
        """
        def read(lbl) -> str | None:
            attr = TDataStd_Name()
            if lbl.FindAttribute(TDataStd_Name.GetID_s(), attr):
                text = TCollection_AsciiString(attr.Get()).ToCString().strip()
                return text or None
            return None

        own = read(label)
        if own:
            return own
        referred = TDF_Label()
        if shape_tool.GetReferredShape_s(label, referred):
            return read(referred)
        return None

    # -- node lookup --------------------------------------------------------

    def _node(self, obj: str) -> tuple[dict, _Node]:
        path, wanted = self._resolve(obj)
        entry = self._read(path)
        if obj not in self._loaded:
            self._loaded.append(obj)

        if wanted is None:
            roots = entry["roots"]
            if len(roots) != 1:
                names = ", ".join(sorted(n.name for n in roots))
                raise Unsupported(
                    f"{path.name} has {len(roots)} root shapes ({names}); "
                    f"address one with '{obj}#<name>'"
                )
            return entry, roots[0]

        matches = entry["by_name"].get(wanted, [])
        if not matches:
            available = ", ".join(sorted(entry["by_name"])) or "none"
            raise Unsupported(
                f"{path.name} has no node named {wanted!r}. Available: {available}"
            )
        if len(matches) > 1:
            where = ", ".join(n.path for n in matches)
            raise Unsupported(
                f"{path.name}: {wanted!r} is ambiguous, it matches {len(matches)} "
                f"nodes ({where}). Refusing to guess which one was meant."
            )
        return entry, matches[0]

    def _shape(self, entry: dict, node: _Node) -> Shape:
        raw = entry["shape_tool"].GetShape_s(node.label)
        if raw.IsNull():
            raise Unsupported(f"{node.path}: node carries no geometry")
        # Shape.cast on the base class is abstract and returns None, so the
        # concrete wrapper has to be chosen explicitly.
        kind = shapetype(raw)
        wrapper = _WRAPPERS.get(kind)
        if wrapper is None:
            raise Unsupported(
                f"{node.path}: shape type {kind} carries no volume -- "
                f"nothing to measure a part against"
            )
        return wrapper(downcast(raw))

    # -- CadAdapter ---------------------------------------------------------

    def state_id(self) -> str:
        """Digest over the bytes of every STEP file read in this run.

        The file *is* the design state, so this is exact -- more so than the
        source hash the build123d adapter has to use.
        """
        digest = hashlib.sha256()
        for path in sorted(self._files):
            digest.update(str(path.name).encode())
            digest.update(self._files[path]["digest"].encode())
        return digest.hexdigest()[:16]

    def objects(self) -> list[str]:
        return list(self._loaded)

    def parameter(self, obj: str, name: str) -> Q | None:
        """Always None. A STEP file is baked geometry -- it has no parameters.

        This is not a missing feature to be filled in later; it is what the
        format is. Named parameters need a live CAD document.
        """
        return None

    def material(self, obj: str) -> Material | None:
        """The XCAF material, if the exporter wrote one.

        FreeCAD usually writes none. Then this returns None and the run reports
        a gap -- it does not invent a density.
        """
        entry, node = self._node(obj)
        try:
            tool = XCAFDoc_DocumentTool.MaterialTool_s(entry["doc"].Main())
            name, density = _read_material(tool, node.label)
        except Exception:
            return None
        if name is None and density is None:
            return None
        return Material(name=name or "unnamed", density=density)

    def measure(self, obj: str, method: str, args: dict | None = None) -> Q:
        if method not in _METHODS:
            raise Unsupported(f"unknown measurement method: {method}")
        entry, node = self._node(obj)
        shape = self._shape(entry, node)
        args = dict(args or {})

        if method == "bbox_size":
            return mm.bbox_size(shape, **args)
        if method == "volume":
            return mm.volume(shape, **args)
        if method == "face_count":
            return mm.face_count(shape, **args)

        override = args.pop("density_g_per_cm3", None)
        if args:
            raise Unsupported(f"mass: unexpected arguments {sorted(args)}")
        if override is not None:
            density = override * ureg.g / ureg.cm**3
        else:
            material = self.material(obj)
            if material is None or material.density is None:
                raise Unsupported(
                    f"{node.path}: the STEP file carries no material, and no "
                    f"density_g_per_cm3 override was given -- cannot compute mass"
                )
            density = material.density
        return mm.mass(shape, density)

    # -- discovery ----------------------------------------------------------

    def catalog(self, objects: list[str] | None = None) -> list[CadTarget]:
        """One target per node of each named file.

        A STEP file has no parameters, so `parameters` is always empty here --
        that absence is the honest difference between a baked file and a script,
        and a proposer should see it rather than infer it.

        An ambiguous node name is listed with a note and no methods: it cannot
        be addressed by name at all, so proposing it would produce an entry the
        adapter would refuse to measure.
        """
        out: list[CadTarget] = []
        for ref in (objects if objects is not None else list(self._files)):
            path, _ = self._resolve(str(ref))
            try:
                entry = self._read(path)
            except Unsupported:
                continue

            file_ref = str(ref).split("#", 1)[0]
            for depth, node in self.tree(file_ref):
                ambiguous = len(entry["by_name"].get(node.name, [])) > 1
                target_ref = file_ref if depth == 0 else f"{file_ref}#{node.name}"
                material = None if ambiguous else self.material(target_ref)
                methods = () if ambiguous else tuple(
                    m for m in METHODS
                    if m != "mass"
                    or (material is not None and material.density is not None)
                )
                out.append(CadTarget(
                    adapter=self.name,
                    reference=target_ref,
                    kind="assembly" if node.is_assembly else "part",
                    name=node.name,
                    methods=methods,
                    depth=depth,
                    note=(
                        f"ambiguous name, {node.path} is one of several"
                        if ambiguous
                        else f"material {material.name}" if material
                        else "no material in the file"
                    ),
                ))
        return out

    def tree(self, obj: str) -> list[tuple[int, _Node]]:
        """Every node of a file with its depth, for explore_cad."""
        path, _ = self._resolve(obj)
        entry = self._read(path)
        out: list[tuple[int, _Node]] = []

        def walk(node: _Node, depth: int) -> None:
            out.append((depth, node))
            for child in node.children:
                walk(child, depth + 1)

        for root in entry["roots"]:
            walk(root, 0)
        return out

    def shape_of(self, obj: str) -> Shape:
        """The wrapped shape of one node -- used by explore_cad for reporting."""
        entry, node = self._node(obj)
        return self._shape(entry, node)


def _read_material(tool, label) -> tuple[str | None, Q | None]:
    """Name and density of the assigned material, or (None, None).

    `GetDensityForShape_s` is the load-bearing part: it returns the density in
    g/cm3 and 0.0 when no material is assigned, which is the case that matters
    -- `mass()` then reports a gap instead of inventing a number. The name is
    best-effort; XCAF's name accessor binds its out-parameters awkwardly, so a
    material with a readable density but an unreadable name comes back as
    "unnamed" rather than being dropped.
    """
    density = tool.GetDensityForShape_s(label)
    if not density:
        return None, None

    name = None
    try:
        attr = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
            name = TCollection_AsciiString(attr.Get()).ToCString().strip() or None
    except Exception:
        name = None

    return name, density * ureg.g / ureg.cm**3
