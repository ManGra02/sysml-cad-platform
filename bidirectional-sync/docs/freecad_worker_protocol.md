# FreeCAD worker — protocol 1

The contract between `FreeCadAdapter` (`src/sysmlcad/adapters/freecad_adapter.py`,
runs in the devcontainer on Python 3.14) and a **headless FreeCAD worker** (its own
container, FreeCAD's own Python, native FreeCAD API: `FreeCAD`, `Part`,
`Spreadsheet`; no build123d, no OCP).

The client side is done and tested against a stand-in worker,
`tests/freecad_fake.py`. That file is this protocol in executable form. If a real
worker answers differently from it, the worker is wrong. If this document and
the fake disagree, report it: one of them has a bug.

**Division of labour.** The worker *reads documents and measures shapes*. Every
rule that decides *which* object or *which* number is meant stays in the client:
- resolving a label to an object
- refusing an ambiguous label
- the root rule
- mass from volume and density
- the density override
- the dimension check on every answer

So the worker can stay small.

---

## 1. Deployment

| | |
|---|---|
| Compose service | `freecad` in `docker/docker-compose.yml` (same project and network as `sysml-api`) |
| Listens on | `0.0.0.0:8765` inside the network. **No host port** (see the port-9000 note in CLAUDE.md) |
| Client setting | `SYSMLCAD_FREECAD_URL=http://freecad:8765` in `.devcontainer/docker-compose.dev.yml` (this project's overlay on the platform devcontainer) |
| Repository mount | the repository root at **the same path as in dev**: `/workspaces/sysml-cad-platform/bidirectional-sync` (the platform devcontainer). All `file` values are relative to `bidirectional-sync/` and must resolve identically on both sides |
| Concurrency | FreeCAD is not thread-safe: one request at a time (`http.server.HTTPServer`, not the threading variant) |
| Timeout | the client waits 120 s by default (`SYSMLCAD_FREECAD_TIMEOUT`) |

**Security.**
- Accept only `*.FCStd` paths that resolve (after `..` and symlinks) inside the repository root.
- `write_limits` accepts only paths under `projects/` or `fixtures/`.
- Refuse everything else with `unsupported`.

## 2. Envelope

Every endpoint answers **HTTP 200** with exactly one of these:

```json
{"ok": <payload>}
{"unsupported": "<one sentence a human can act on>"}
```

- **`unsupported`** means "cannot answer this question for this object". The
  client records it as a gap in the run, so the sentence ends up in front of an
  engineer. Say what is missing and where.
- **Anything else** is treated as a worker fault and also becomes a gap: a
  non-200 status, a body that is not JSON, or JSON with neither key. A worker
  fault never crashes a verification run.

## 3. Quantities

Every number with a unit travels like this:

```json
{"value": 100.0, "unit": [1, 0, 0, 0, 0, 0, 0, 0]}
```

| Field | Content |
|---|---|
| `value` | `quantity.Value`, i.e. FreeCAD's **internal** value. Never a string formatted with the user's unit schema |
| `unit` | `list(quantity.Unit.Signature)`: 8 integers in FreeCAD's order: Length, Mass, Time, ElectricCurrent, Temperature, AmountOfSubstance, LuminousIntensity, Angle. The internal base units are mm, kg, s, A, K, mol, cd, ° |

Examples:

| Quantity | On the wire |
|---|---|
| 100 mm | `{"value": 100.0, "unit": [1,0,0,0,0,0,0,0]}` |
| 6e6 mm³ | `{"value": 6000000.0, "unit": [3,0,0,0,0,0,0,0]}` |
| 2.70 g/cm³ | `{"value": 2.7e-06, "unit": [-3,1,0,0,0,0,0,0]}` (kg/mm³) |
| 45° | `{"value": 45.0, "unit": [0,0,0,0,0,0,0,1]}` |
| a plain count | `{"value": 6.0, "unit": [0,0,0,0,0,0,0,0]}` |

Values must be finite. The unit must be exactly 8 integers.

## 4. Endpoints

All paths are prefixed with `/v1`. Request bodies are JSON.

### `GET /v1/health`

```json
{"ok": {"freecad": "1.0.2", "protocol": 1}}
```

The client refuses any `protocol` other than 1.

### `POST /v1/document`

Request: `{"file": "projects/cube_freecad/cube.FCStd"}`

Open the document (or reuse a cached one whose mtime and size are unchanged),
**`recompute()` it in memory**, and describe it:

```json
{"ok": {
  "objects": [
    {"label": "Gearbox", "name": "Part",    "type": "App::Part",        "parent": null,
     "has_shape": true, "error": null, "material": null},
    {"label": "Housing", "name": "Body",    "type": "PartDesign::Body", "parent": "Gearbox",
     "has_shape": true, "error": null,
     "material": {"name": "Aluminum", "density": {"value": 2.7e-06, "unit": [-3,1,0,0,0,0,0,0]}}}
  ],
  "parameters": {
    "Params.Length": {"value": 90.0, "unit": [1,0,0,0,0,0,0,0]},
    "Pad.Length":    {"value": 40.0, "unit": [1,0,0,0,0,0,0,0]}
  }
}}
```

**Which objects to list.** Those a requirement can be about: parts and
assemblies, **not** the features inside them.
- **List:** `PartDesign::Body`; `App::Part` and Assembly containers; `App::Link`
  to one of these; and any `Part::Feature`-derived object that is **not consumed**
  by another object. Not consumed means its `InList` holds no feature, boolean
  or Body that uses it as a base, other than plain containers.
- **Do not list:** Pads, Pockets, Sketches, datum objects, spreadsheets, VarSets,
  or the operands of a boolean.

**Fields of each object:**

| Field | Content |
|---|---|
| `label` | `obj.Label`, exactly as written. The client addresses by label |
| `name` | `obj.Name`. The client sends it back to `/v1/measure`, so it must identify the object uniquely |
| `type` | `obj.TypeId`, for display only |
| `parent` | **label** of the nearest listed container (`App::Part`, Assembly), or `null` at the top |
| `has_shape` | whether `Part.getShape(obj)` is non-null |
| `error` | `null`, or a short text when the object (or a feature it depends on) is invalid or still touched after `recompute()`, e.g. `"Pocket: Sketch is over-constrained"`. The client then refuses to measure that object. A stale shape is never measured |
| `material` | the **effective** material: the object's own, otherwise the one it inherits from its Body or container. FreeCAD 1.0: `obj.ShapeMaterial` and its `PhysicalProperties["Density"]`; older documents: the `Material` property or an `App::MaterialObject`. Send `null` when there is none. A density of 0 or none is also treated as no density by the client, so it never computes a zero mass |

**Parameters** are document-wide, keyed by name. Include every value that has a
unit:

| Source | Key | Value |
|---|---|---|
| Spreadsheet alias | `<SheetLabel>.<alias>` | `sheet.get(alias)` as a quantity. A plain number is dimensionless, and the client's dimension gate then refuses it for a length |
| Quantity property of a listed object or one of its features (`App::PropertyLength`, `PropertyDistance`, `PropertyAngle`, `PropertyQuantity`, …) | `<FeatureLabel>.<Property>`, e.g. `Pad.Length`, `Box.Height` | the property value |
| VarSet property (FreeCAD 1.0) | `<VarSetLabel>.<Property>` | the property value |
| Named sketch constraint | `<SketchLabel>.<ConstraintName>` | the constraint value, as length or angle |

Leave out the sync's own sheet (§ 5). Its values are limits, not parameters.

### `POST /v1/measure`

Request:
```json
{"file": "...", "object": "<obj.Name>", "method": "bbox_size", "args": {"axis": "X"}}
```

Answer: `{"ok": <quantity>}`. The shape is `Part.getShape(obj, transform=True)`
(placements applied, links resolved), measured on the recomputed document.

| method | args | answer | semantics |
|---|---|---|---|
| `bbox_size` | `axis`: `"X"`/`"Y"`/`"Z"` (always sent) | length | `shape.optimalBoundingBox(False, False)`, then `XLength`/`YLength`/`ZLength`. **Not** `shape.BoundBox`: that one is not tight on curved faces |
| `volume` | — | length³ | `shape.Volume` |
| `face_count` | — | dimensionless | `len(shape.Faces)` |
| `cylinder_radius` | `kind`: `null`/`"hole"`/`"boss"`; `axis`: `null`/`"X"`/`"Y"`/`"Z"` | length | radius of the **one** cylindrical feature, see below |

The client does not send `mass` or `parameter`; it answers both itself.

**`cylinder_radius`.** This must give the same result as
`src/sysmlcad/adapters/measurements.py::cylinder_radius`:
1. Take every face whose `Surface` is a `Part.Cylinder`.
2. Decide its kind: `hole` when the face normal at the parameter mid-point points
   towards the axis (material outside the surface), else `boss`. Use the
   orientation-respecting normal (`face.normalAt(u, v)`). The orientation flag
   alone is not enough.
3. Apply the filters: keep only `kind`, if given; keep only axes parallel to
   `axis`, if given.
4. Group the faces into features. Two faces are the same feature when kind
   matches, the radii differ by at most 1e-4 mm, and the axis lines coincide
   within 1e-4 mm. Parallel axes are not enough.
5. Exactly one feature must remain. **None or more than one is `unsupported`**,
   naming what was found, e.g. "2 cylindrical features (hole r=8 …, boss r=2 …)
   -- narrow it with kind or axis". Never return the first one.

### `POST /v1/write_limits`

Request:
```json
{"file": "projects/cube_freecad/cube.FCStd", "sheet": "SysML",
 "values": {"MaxLength": {"value": 100.0, "unit": [1,0,0,0,0,0,0,0]}},
 "apply": false}
```

Answer:
```json
{"ok": {"changes": [{"alias": "MaxLength", "old": null,
                     "new": {"value": 100.0, "unit": [1,0,0,0,0,0,0,0]}}],
        "saved": false}}
```

Rules. These are the whole safety story of write-back:
1. **The managed sheet.** `sheet` is a spreadsheet **label**. If no such sheet
   exists, the worker creates it (on `apply`) with a **marker**: cell `A1` =
   `managed by sysmlcad -- do not edit`. If the sheet exists **without** that
   marker, answer `unsupported` and touch nothing. This means a designer's own
   sheet is never written, even on a name clash.
2. **Layout** from row 2 down: column A is the alias as text, column B is the
   value with unit (e.g. `=100 mm`) and `setAlias("B<n>", alias)`, column C is
   `"sysmlcad"`. The client only ever sends limits. The worker **never** writes
   anywhere outside this sheet, and never to a cell whose column C does not read
   `sysmlcad`.
3. **`changes`** lists only aliases whose value differs (`old` is `null` for a
   new alias). Compare the values as quantities, not as text. An alias already
   in the sheet but absent from `values` stays untouched; deleting limits is
   not part of protocol 1.
4. **`apply: false`** changes nothing, in memory or on disk.
5. **`apply: true`** with changes: write, `recompute()`, `saveAs` to the same
   path, then invalidate the cache. `saved: true` means the file on disk
   changed. Without changes, do not save, because saving alone changes the
   file digest that the client records as the design state.

## 5. What the client already guarantees (no need to repeat)

- **Mapping arguments are checked** before any request, so the worker never sees
  a typo'd argument: `bbox_size` gets exactly `axis`, `cylinder_radius` gets
  `kind`/`axis` with valid values.
- **`/v1/measure` only sees valid objects.** It is only called for an object
  that came from `/v1/document` with `error: null` and `has_shape: true`.
- **Every answer is dimension-checked.** A `volume` that comes back as a length
  is refused.
- **The design state** is the SHA-256 of the file bytes, read locally by the
  client. The worker does not report it.

## 6. Acceptance

Before the client's integration tests can run against the real worker:

1. `make freecad-health` (in dev) prints the FreeCAD version and `protocol 1`.
2. **Fixtures** are generated by a script in the worker container and committed
   under `fixtures/freecad/` (`.FCStd` is binary, like the STEP fixtures):
   - `cube.FCStd`: a `Part::Box` whose Length, Width and Height (100/200/300 mm)
     are driven by spreadsheet `Params` (aliases `Length`, `Width`, `Height`),
     material aluminium.
   - `cube_rotated.FCStd`: the same box, turned 45° about Z.
   - `housing_pd.FCStd`: a PartDesign Body (Sketch → Pad with `Pad.Length`,
     Pocket as a bore) plus a VarSet.
   - `gearbox.FCStd`: `fixtures/step/gearbox.step` imported, labels `Housing`
     and `Cover`.
3. **Equivalence.** For `gearbox.FCStd#Housing` and `#Cover`, the worker's
   `bbox_size` (X/Y/Z), `volume` and `cylinder_radius(kind="hole")` must equal
   the step adapter's numbers on `fixtures/step/gearbox.step` to 1e-6 relative.
   This test holds the third copy of the measurement vocabulary to the other two.
4. **Rotation.** `cube_rotated.FCStd`: `bbox_size X` is about 212.1 mm, and
   `Params.Length` is still 100 mm.
5. **Write-back.** `write_limits` on a copy of `cube.FCStd` with `apply: true`.
   Afterwards the document opens in FreeCAD, `=SysML.MaxLength` is usable in an
   expression, and a second identical call returns `changes: []` and does not
   save.
