"""CAD side backed by native FreeCAD documents (`.FCStd`), through a worker.

FreeCAD brings its own Python and cannot be imported into this one (the
devcontainer runs 3.14), so the geometry lives in a separate process: a
headless FreeCAD worker in its own container, spoken to over JSON/HTTP. This
module is the client half. It imports no geometry kernel and no FreeCAD -- the
seam rule holds on both sides of the wire.

The contract with the worker is `docs/freecad_worker_protocol.md`, version
`PROTOCOL`. Every rule that decides *which* object or *which* number is meant
lives here, on this side, so that a worker can be replaced without moving any
of them: label resolution, ambiguity, the root rule, mass from volume and
density, the density override. The worker reads documents and measures shapes.

WHAT A DOCUMENT GIVES THAT A STEP EXPORT DOES NOT
-------------------------------------------------
* named parameters -- spreadsheet aliases (`Params.Length`), feature
  properties (`Pad.Length`), VarSet properties -- so a length can be the
  *stated* length instead of a bounding box (`parameter(name)`)
* the material the designer assigned, so `mass` needs no override
* labels exactly as the designer wrote them
* a recomputed state: the worker recomputes before it answers, and an object
  that fails to recompute is reported, never measured stale

ADDRESSING
----------
    projects/cube_freecad/cube.FCStd#Box     one object, by its LABEL
    projects/cube_freecad/cube.FCStd         the one root object, if there is one

Paths are repository-relative; the worker mounts the repository at the same
path. A label matching more than one object is an error, never a choice.

WHEN THE WORKER IS NOT THERE
----------------------------
Every failure to reach it -- no URL configured, connection refused, timeout, a
malformed answer -- is `Unsupported`, which a run records as a gap. A missing
FreeCAD container costs the FreeCAD-mapped requirements, never the run.
"""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..units import Q, ureg
from . import (
    METHODS,
    NEEDS_PARAMETERS,
    CadTarget,
    LimitChange,
    Material,
    Unsupported,
    check_args,
    check_density,
)

ROOT = Path(__file__).resolve().parents[3]

#: Where the worker listens. No default on purpose: a guessed host would turn
#: "not configured" into a timeout that reads like a network fault.
URL_ENV = "SYSMLCAD_FREECAD_URL"
TIMEOUT_ENV = "SYSMLCAD_FREECAD_TIMEOUT"

#: The protocol version this client speaks. The worker states its own in
#: `/v1/health`; a mismatch is refused rather than half-understood.
PROTOCOL = 1

#: FreeCAD's unit signature, in FreeCAD's order, and the internal unit of each
#: base dimension. FreeCAD computes in mm, kg, s, A, K, mol, cd and degrees;
#: `Quantity.Value` is in exactly these, whatever the user's unit schema shows.
_SIGNATURE = (
    ("[length]", ureg.mm),
    ("[mass]", ureg.kg),
    ("[time]", ureg.s),
    ("[current]", ureg.ampere),
    ("[temperature]", ureg.kelvin),
    ("[substance]", ureg.mol),
    ("[luminosity]", ureg.candela),
)
_ANGLE_UNITS = {"degree", "radian", "arcminute", "arcsecond", "turn"}

#: Measured by the worker on the shape. `mass` and `parameter` are answered
#: here, from what the document listing already says.
_GEOMETRIC = ("bbox_size", "volume", "face_count", "cylinder_radius")


# --------------------------------------------------------------------------
# Quantities on the wire
# --------------------------------------------------------------------------

def decode_quantity(data) -> Q:
    """`{"value": 100.0, "unit": [1, 0, 0, 0, 0, 0, 0, 0]}` -> 100 mm.

    Exact by construction: the value is FreeCAD's internal one and the unit is
    rebuilt from the signature, so no unit *name* -- which depends on the user's
    unit schema -- is ever parsed.
    """
    if not isinstance(data, dict):
        raise Unsupported(f"FreeCAD worker: a quantity must be an object, not {data!r}")
    value, signature = data.get("value"), data.get("unit")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Unsupported(f"FreeCAD worker: quantity value {value!r} is not a finite number")
    if (
        not isinstance(signature, list) or len(signature) != 8
        or not all(isinstance(e, int) and not isinstance(e, bool) for e in signature)
    ):
        raise Unsupported(f"FreeCAD worker: unit signature {signature!r} is not 8 integers")

    unit = ureg.dimensionless
    for (_, base), exponent in zip(_SIGNATURE, signature[:7]):
        if exponent:
            unit = unit * base**exponent
    if signature[7]:
        unit = unit * ureg.degree ** signature[7]
    return Q(float(value), unit)


def encode_quantity(quantity: Q) -> dict:
    """The inverse of `decode_quantity`, for limits written into a document."""
    dims = quantity.dimensionality
    exponents = []
    for key, _ in _SIGNATURE:
        exponent = dims.get(key, 0)
        if exponent != int(exponent):
            raise Unsupported(f"{quantity:~P}: fractional dimension, no FreeCAD unit for it")
        exponents.append(int(exponent))
    unknown = set(dims) - {key for key, _ in _SIGNATURE}
    if unknown:
        raise Unsupported(f"{quantity:~P}: dimension {sorted(unknown)} has no FreeCAD unit")

    base = ureg.dimensionless
    for (_, unit), exponent in zip(_SIGNATURE, exponents):
        if exponent:
            base = base * unit**exponent

    angle = 0
    # pint treats an angle as dimensionless; FreeCAD does not. Only a quantity
    # actually expressed in an angle unit is sent as one.
    if not any(exponents) and str(quantity.units) in _ANGLE_UNITS:
        angle, base = 1, ureg.degree
    return {"value": float(quantity.to(base).magnitude), "unit": exponents + [angle]}


# --------------------------------------------------------------------------
# A document, as the worker describes it
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class _Object:
    label: str
    name: str                     # FreeCAD's internal name, unique per document
    type: str = ""
    parent: str | None = None     # the containing object's LABEL
    has_shape: bool = True
    error: str | None = None      # recompute failure, or None
    material: Material | None = None


@dataclass
class _Document:
    path: str
    objects: list[_Object]
    parameters: dict[str, Q]
    digest: str
    by_label: dict[str, list[_Object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for obj in self.objects:
            self.by_label.setdefault(obj.label, []).append(obj)

    @property
    def roots(self) -> list[_Object]:
        return [o for o in self.objects if o.parent is None and o.has_shape]

    def depth(self, obj: _Object) -> int:
        depth, seen, parent = 0, {obj.label}, obj.parent
        while parent is not None and parent not in seen:
            seen.add(parent)
            depth += 1
            owners = self.by_label.get(parent, [])
            parent = owners[0].parent if len(owners) == 1 else None
        return depth

    def children(self, obj: _Object) -> list[_Object]:
        return [o for o in self.objects if o.parent == obj.label]


def _material(data) -> Material | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise Unsupported(f"FreeCAD worker: material must be an object, not {data!r}")
    density = data.get("density")
    density = None if density is None else decode_quantity(density)
    if density is not None and density.dimensionality != (ureg.kg / ureg.m**3).dimensionality:
        raise Unsupported(f"FreeCAD worker: density {density:~P} is not a mass per volume")
    if density is not None and not density.magnitude > 0:
        density = None    # FreeCAD's "no density" -- never a zero-mass part
    name = str(data.get("name") or "").strip()
    if not name and density is None:
        return None
    return Material(name=name or "unnamed", density=density)


# --------------------------------------------------------------------------
# The adapter
# --------------------------------------------------------------------------

class FreeCadAdapter:
    """Addresses FreeCAD documents by path, with an optional object label after '#'."""

    name = "freecad"

    def __init__(
        self,
        url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        root: Path | None = None,
        timeout: float | None = None,
    ):
        self._url = (url or os.environ.get(URL_ENV) or "").rstrip("/")
        self._transport = transport
        self._root = Path(root) if root else ROOT
        self._timeout = timeout or float(os.environ.get(TIMEOUT_ENV) or 120)
        self._client: httpx.Client | None = None
        self._checked = False
        self._documents: dict[str, _Document] = {}
        self._loaded: list[str] = []

    # -- the wire -----------------------------------------------------------

    def _http(self) -> httpx.Client:
        if not self._url:
            raise Unsupported(
                f"no FreeCAD worker configured: set {URL_ENV} "
                f"(e.g. http://freecad:8765) -- see docs/freecad_worker_protocol.md"
            )
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._url, timeout=self._timeout, transport=self._transport
            )
        return self._client

    def _call(self, method: str, path: str, body: dict | None = None):
        """One request; whatever goes wrong comes back as `Unsupported`."""
        client = self._http()
        try:
            response = client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise Unsupported(
                f"FreeCAD worker at {self._url} not reachable ({type(exc).__name__}: {exc})"
            ) from None
        if response.status_code != 200:
            raise Unsupported(
                f"FreeCAD worker answered HTTP {response.status_code} to {path}: "
                f"{response.text[:200]}"
            )
        try:
            envelope = response.json()
        except ValueError:
            raise Unsupported(f"FreeCAD worker: {path} did not answer JSON") from None
        if isinstance(envelope, dict) and "unsupported" in envelope:
            raise Unsupported(str(envelope["unsupported"]))
        if not isinstance(envelope, dict) or "ok" not in envelope:
            raise Unsupported(f"FreeCAD worker: {path} answered without 'ok' or 'unsupported'")
        return envelope["ok"]

    def _check_protocol(self) -> None:
        if self._checked:
            return
        health = self._call("GET", "/v1/health")
        version = health.get("protocol") if isinstance(health, dict) else None
        if version != PROTOCOL:
            raise Unsupported(
                f"FreeCAD worker speaks protocol {version!r}, this client {PROTOCOL} "
                f"-- refusing to half-understand it"
            )
        self._checked = True

    def health(self) -> dict:
        """What the worker says about itself -- FreeCAD version, protocol."""
        self._checked = False
        self._check_protocol()
        return self._call("GET", "/v1/health")

    # -- reading ------------------------------------------------------------

    def _resolve(self, obj: str) -> tuple[str, str | None]:
        ref, _, label = obj.partition("#")
        return ref, (label or None)

    def _local(self, ref: str) -> Path:
        path = Path(ref)
        return path if path.is_absolute() else self._root / path

    def _document(self, ref: str) -> _Document:
        if ref in self._documents:
            return self._documents[ref]
        local = self._local(ref)
        if not local.is_file():
            raise Unsupported(f"no FreeCAD document at {local}")
        if local.suffix.lower() != ".fcstd":
            raise Unsupported(f"{local.name} is not a FreeCAD document (.FCStd)")

        self._check_protocol()
        data = self._call("POST", "/v1/document", {"file": ref})
        if not isinstance(data, dict) or not isinstance(data.get("objects"), list):
            raise Unsupported(f"FreeCAD worker: {ref}: document answer has no object list")

        objects = []
        for item in data["objects"]:
            if not isinstance(item, dict) or not item.get("label") or not item.get("name"):
                raise Unsupported(f"FreeCAD worker: {ref}: object without label/name: {item!r}")
            objects.append(_Object(
                label=str(item["label"]),
                name=str(item["name"]),
                type=str(item.get("type") or ""),
                parent=item.get("parent"),
                has_shape=bool(item.get("has_shape", True)),
                error=item.get("error") or None,
                material=_material(item.get("material")),
            ))
        raw_parameters = data.get("parameters") or {}
        if not isinstance(raw_parameters, dict):
            raise Unsupported(f"FreeCAD worker: {ref}: parameters must be an object")
        parameters = {str(k): decode_quantity(v) for k, v in raw_parameters.items()}

        document = _Document(
            path=ref,
            objects=objects,
            parameters=parameters,
            digest=hashlib.sha256(local.read_bytes()).hexdigest()[:16],
        )
        self._documents[ref] = document
        return document

    def _object(self, obj: str) -> tuple[_Document, _Object]:
        ref, label = self._resolve(obj)
        document = self._document(ref)
        if obj not in self._loaded:
            self._loaded.append(obj)

        if label is None:
            roots = document.roots
            if len(roots) != 1:
                names = ", ".join(sorted(o.label for o in roots)) or "none"
                raise Unsupported(
                    f"{Path(ref).name} has {len(roots)} root objects ({names}); "
                    f"address one with '{ref}#<label>'"
                )
            return document, roots[0]

        matches = document.by_label.get(label, [])
        if not matches:
            available = ", ".join(sorted(document.by_label)) or "none"
            raise Unsupported(
                f"{Path(ref).name} has no object labelled {label!r}. Available: {available}"
            )
        if len(matches) > 1:
            names = ", ".join(o.name for o in matches)
            raise Unsupported(
                f"{Path(ref).name}: label {label!r} is ambiguous, it matches "
                f"{len(matches)} objects ({names}). Refusing to guess which one was meant."
            )
        return document, matches[0]

    def _measurable(self, document: _Document, item: _Object) -> None:
        if item.error:
            raise Unsupported(
                f"{document.path}#{item.label}: FreeCAD could not recompute it "
                f"({item.error}) -- a stale shape is not measured"
            )
        if not item.has_shape:
            raise Unsupported(f"{document.path}#{item.label} carries no shape")

    # -- CadAdapter ---------------------------------------------------------

    def state_id(self) -> str:
        """Digest over the bytes of every document read in this run.

        Read locally, not from the worker: the file in the repository is the
        design state, whoever measured it. Saving an unchanged document in
        FreeCAD changes this too -- an FCStd is a zip with timestamps.
        """
        digest = hashlib.sha256()
        for ref in sorted(self._documents):
            digest.update(Path(ref).name.encode())
            digest.update(self._documents[ref].digest.encode())
        return digest.hexdigest()[:16]

    def objects(self) -> list[str]:
        return list(self._loaded)

    def parameter(self, obj: str, name: str) -> Q | None:
        """A named parameter of the object's document, or None.

        Document-wide, like a script's module constants: a spreadsheet alias
        belongs to no single object, and `Pad.Length` is addressed by its
        feature's label already.
        """
        document, _ = self._object(obj)
        return document.parameters.get(name)

    def material(self, obj: str) -> Material | None:
        _, item = self._object(obj)
        return item.material

    def measure(self, obj: str, method: str, args: dict | None = None) -> Q:
        if method not in METHODS:
            raise Unsupported(f"unknown measurement method: {method}")
        args = dict(args or {})
        check_args(method, _SIGNATURES[method], **args)
        document, item = self._object(obj)

        if method == "parameter":
            value = document.parameters.get(args["name"])
            if value is None:
                raise Unsupported(
                    f"{Path(document.path).name} has no parameter {args['name']!r}"
                    + (f". Available: {', '.join(sorted(document.parameters))}"
                       if document.parameters else "")
                )
            return value

        self._measurable(document, item)

        if method == "mass":
            override = args.get("density_g_per_cm3")
            if override is not None:
                density = check_density(override) * ureg.g / ureg.cm**3
            elif item.material is not None and item.material.density is not None:
                density = item.material.density
            else:
                raise Unsupported(
                    f"{document.path}#{item.label} has no material with a density, and "
                    f"no density_g_per_cm3 override was given -- cannot compute mass"
                )
            volume = self._geometric(document, item, "volume", {})
            return (volume * density).to(ureg.kg)

        return self._geometric(document, item, method, args)

    def _geometric(self, document: _Document, item: _Object, method: str, args: dict) -> Q:
        if method == "bbox_size":
            axis = str(args.get("axis", "X")).upper()
            if axis not in ("X", "Y", "Z"):
                raise Unsupported(f"bbox_size: axis must be X, Y or Z, not {args.get('axis')!r}")
            args = {"axis": axis}
        elif method == "cylinder_radius":
            if args.get("kind") not in (None, "hole", "boss"):
                raise Unsupported(f"cylinder_radius: kind must be hole or boss, not {args['kind']!r}")
            if args.get("axis") is not None:
                if str(args["axis"]).upper() not in ("X", "Y", "Z"):
                    raise Unsupported(
                        f"cylinder_radius: axis must be X, Y or Z, not {args['axis']!r}"
                    )
                args = {**args, "axis": str(args["axis"]).upper()}
        result = decode_quantity(self._call("POST", "/v1/measure", {
            "file": document.path, "object": item.name, "method": method, "args": args,
        }))
        expected = _DIMENSIONS[method]
        if result.dimensionality != expected:
            raise Unsupported(
                f"FreeCAD worker: {method} came back as {result:~P}, "
                f"expected dimension {expected}"
            )
        return result

    # -- discovery ----------------------------------------------------------

    def catalog(self, objects: list[str] | None = None) -> list[CadTarget]:
        """One target per object of each named document.

        A document the worker cannot read is listed as ONE target with no
        methods and the reason in its note: "this exists and cannot be measured
        right now" is information, and silently dropping it would make a
        missing worker look like a missing file.
        """
        out: list[CadTarget] = []
        for ref in (objects if objects is not None else list(self._documents)):
            file_ref = str(ref).split("#", 1)[0]
            try:
                document = self._document(file_ref)
            except Unsupported as exc:
                out.append(CadTarget(
                    adapter=self.name, reference=file_ref, kind="part",
                    name=Path(file_ref).stem, methods=(), note=f"not readable: {exc}",
                ))
                continue

            single_root = len(document.roots) == 1
            for item in document.objects:
                if not item.has_shape:
                    continue
                depth = document.depth(item)
                ambiguous = len(document.by_label[item.label]) > 1
                reference = (
                    file_ref if single_root and item is document.roots[0]
                    else f"{file_ref}#{item.label}"
                )
                has_density = item.material is not None and item.material.density is not None
                methods = () if (ambiguous or item.error) else tuple(
                    m for m in METHODS
                    if (m != "mass" or has_density)
                    and (m not in NEEDS_PARAMETERS or document.parameters)
                )
                if ambiguous:
                    note = f"ambiguous label, one of {len(document.by_label[item.label])}"
                elif item.error:
                    note = f"does not recompute: {item.error}"
                elif item.material is not None:
                    note = f"material {item.material.name}"
                else:
                    note = "no material in the document"
                out.append(CadTarget(
                    adapter=self.name,
                    reference=reference,
                    kind="assembly" if document.children(item) else "part",
                    name=item.label,
                    methods=methods,
                    parameters=dict(document.parameters),
                    note=note,
                    depth=depth,
                ))
        return out

    # -- writing (WritableAdapter) ------------------------------------------

    def write_limits(
        self, document: str, sheet: str, values: dict[str, Q], apply: bool = False
    ) -> list[LimitChange]:
        """Write requirement limits into the managed sheet `sheet`.

        The worker owns the FreeCAD side of the rules -- it creates the sheet
        with its marker, refuses a sheet without one, never touches a cell it
        did not write, recomputes and saves. This side decides *what* is
        written. With `apply=False` nothing is saved and the result is the diff.
        """
        ref, label = self._resolve(document)
        if label is not None:
            raise Unsupported(f"limits are written into a document, not into {document!r}")
        if not self._local(ref).is_file():
            raise Unsupported(f"no FreeCAD document at {self._local(ref)}")
        self._check_protocol()
        data = self._call("POST", "/v1/write_limits", {
            "file": ref,
            "sheet": sheet,
            "values": {alias: encode_quantity(q) for alias, q in sorted(values.items())},
            "apply": bool(apply),
        })
        if not isinstance(data, dict) or not isinstance(data.get("changes"), list):
            raise Unsupported("FreeCAD worker: write_limits answered without a change list")
        changes = []
        for item in data["changes"]:
            old = item.get("old")
            changes.append(LimitChange(
                alias=str(item["alias"]),
                old=None if old is None else decode_quantity(old),
                new=decode_quantity(item["new"]),
            ))
        if apply:
            # The document changed on disk; what this run read of it is stale.
            self._documents.pop(ref, None)
        return changes

    def tree(self, obj: str) -> list[tuple[int, CadTarget]]:
        """Every target of a document with its depth, for explore_cad."""
        return [(t.depth, t) for t in self.catalog([obj])]


# --------------------------------------------------------------------------
# What each method takes, and what it yields
# --------------------------------------------------------------------------

def _bbox_size(axis: str = "X"): ...
def _volume(): ...
def _face_count(): ...
def _cylinder_radius(kind: str | None = None, axis: str | None = None): ...
def _mass(density_g_per_cm3: float | None = None): ...
def _parameter(name: str): ...


#: Signatures for `check_args`, so a typo in `args:` is one gap here exactly as
#: it is in the other two adapters -- and is caught before a request is sent.
_SIGNATURES = {
    "bbox_size": _bbox_size,
    "volume": _volume,
    "face_count": _face_count,
    "cylinder_radius": _cylinder_radius,
    "mass": _mass,
    "parameter": _parameter,
}

#: What the worker must answer with. Checked, because a worker that reports a
#: volume in mm is a worker bug that would otherwise become a verdict.
_DIMENSIONS = {
    "bbox_size": ureg.mm.dimensionality,
    "volume": (ureg.mm**3).dimensionality,
    "face_count": ureg.dimensionless.dimensionality,
    "cylinder_radius": ureg.mm.dimensionality,
}


def main() -> int:
    """`python -m sysmlcad.adapters.freecad_adapter` -- is the worker there?"""
    try:
        health = FreeCadAdapter().health()
    except Unsupported as exc:
        print(f"FreeCAD worker: NOT AVAILABLE -- {exc}")
        return 1
    print(f"FreeCAD worker: {health.get('freecad', '?')}, protocol {health.get('protocol')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
