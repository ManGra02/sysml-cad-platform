# Roadmap

Guiding principle: get the thin end-to-end thread working first, then add
breadth. Every stage builds on a verified predecessor.

The target system is described in `goal_spec.txt` (SRS v0.1, "Bi-Directional
Synchronization") and the HNI/IEM use-case slides. This roadmap deviates from
both in a few places; where it does, the reason is written down.

| Stage | Content | Status |
|---|---|---|
| 0–3 | Infrastructure, extraction, measurement core, verification engine, CI | **done** |
| A | Re-anchor the mapping on parts; CAD adapter seam; three verdicts; provenance | **done** |
| A2 | STEP adapter — read CAD files the project did not author | **done** |
| B | Change-impact analysis | open |
| C | Evidence log and reports | open |
| D | MCP server | open |
| E | Gates and human confirmation | open |
| F | FreeCAD adapter — the parametric half STEP cannot do | open |
| G | Ownership-gated writes | open |
| H | AI mapping proposals | open |

Ordering constraints that must not be broken: **gates before writes**, **gates
before AI**, **adapter seam before FreeCAD**.

---

## Three principles that hold across every stage

**1. AI proposes; it never evaluates.** The slides read as though the AI does
the verification ("AI can read both systems and then do the Automated
Target/Actual Verification"). It must not. An AI component proposes mappings
and speaks natural language; once a mapping is confirmed it is an ordinary
deterministic rule, and its origin no longer influences any result. That is
what SRS FREQ-5 and NFREQ-1 actually require, and slide 9's own phrase
"concrete adapter per attribute … deterministic for auditability" concedes it.

**2. Mapping validity and requirement satisfaction are different questions.**
Absent from the SRS, and the easiest thing here to get wrong. Gates check the
*assignment* (dimension, existence, uniqueness, plausibility). The verification
engine checks *satisfaction*. A correctly mapped part that is too long is a
violation, not a bad mapping — and it is precisely the case the system exists
to report. The original plan wanted to persist a mapping only if the
requirement was satisfied, which would both hide real violations and persist
wrong mappings that happen to pass.

**3. "We did not check this" is not "this passed."** Gaps — no confirmed
mapping, or a quantity the CAD side cannot supply — are carried through the
run and reported, never substituted with a value (SRS FREQ-2) and never
silently counted as coverage.

---

## Stage A — Re-anchor and seam ✅

No new user-visible features; the refactor that lets everything after it work.

**A.1 The mapping is anchored on parts, not on requirements.** Previously
`mapping.yaml` mapped `requirement_id → cad_module + method`. Both source
documents ask for something else — slide 9's table is `partdef → component`,
`attribute → parameter`, and FREQ-3 defines an entry as "the identifier of the
system model element and the name of its attribute, the CAD object and its
parameter".

The link needed for this was already in the model and was being thrown away.
`satisfy maxLengthCheck by motorHousing;` serialises as:

```
SatisfyRequirementUsage
 ├─ ReferenceSubsetting.general → RequirementUsage → FeatureTyping.general → RequirementDefinition
 └─ SubjectMembership.memberElement → ReferenceUsage → FeatureValue
                                    → FeatureReferenceExpression
                                    → Membership.memberElement → PartUsage
```

`extract.resolve_satisfies()` now walks it. The extractor used to report the
subject *parameter* of the definition (`housing`); it now reports the part the
model says is constrained (`motorHousing`), with its element id and the link
path that proves the relation. Consequences: far fewer mapping entries, a new
requirement on an already-mapped part needs no new entry, and change-impact
analysis has the path it must be able to cite.

**A.2 The mapping stays YAML. The evidence log will not.** ROADMAP previously
said SQLite replaces `mapping.yaml`. FREQ-3 disagrees and is right: the mapping
must be "human-readable and … placed under version control". It is design
intent and belongs in review. The append-only *evidence* log is the thing that
wants a database. Two stores, two jobs.

**A.3 A CAD adapter seam.** `sysmlcad/adapters/` defines `CadAdapter`; nothing
above it imports a geometry kernel. `Build123dAdapter` is the reference
implementation and stays as the offline CI backend. Measurement method names
(`bbox_size`, `volume`, `mass`, `face_count`) are adapter-independent
vocabulary; an adapter raises `Unsupported` for what it cannot do rather than
returning a substituted value.

**A.4 Three verdicts and provenance.** `compliant` / `within_tolerance` /
`violated` per FREQ-7, with the deviation, and tolerance declared on the
mapping entry. `RunContext` records the SysML commit id, the CAD `state_id`,
the mapping digest and a timestamp — FREQ-1 requires results be attributable
to an exact model state, and the commit id used to be fetched and discarded.

**A.5 A `direction` field exists but nothing writes yet.** `sysml_owns` /
`cad_owns` / `both`, so enabling writes in Stage G is a change of behaviour
rather than a schema migration.

**Still open from Stage A** (both need a running API server):
- Extend the reference model to a two-part assembly with an interface
  dimension and an assembly-level mass budget. A single part cannot exercise
  part-anchored mapping properly. *The CAD half of this exists already*:
  `cad/gearbox.py` builds Housing + Cover around a shared `BORE_RADIUS_MM`, and
  `fixtures/step/gearbox.step` is its export. What is missing is the SysML side
  — `models/motor_housing.sysml` is still one part, one `satisfy` per
  requirement — and a `mapping.yaml` with more than one `parts:` entry. Until
  that exists, "one requirement, one part" is untested by anything but design.
- Publish `airbus/apollo-11-sysml-v2` and run `explore.py` over it. Expect the
  "one comparison per requirement" assumption to break first. Cheap, hard
  evidence for which extractor simplification to fix next.

---

## Stage A2 — STEP adapter ✅

Before this, a "CAD object" was a Python module: applying the project to a new
model meant rewriting the part as a build123d script. Now a file exported from
any CAD system is measurable, and the seam from stage A is what made it a
new file rather than a rewrite.

**Why STEP.** ISO 10303, exported by FreeCAD, CATIA, Creo, NX, SolidWorks and
Onshape alike, and readable with **no new dependency** — build123d already
brings OCCT, including the XCAF layer that carries names, assembly structure
and materials. B-Rep solids mean all four measurement methods work unchanged;
the round trip of the reference part differs by 2.9·10⁻¹⁰ mm³.

*Rejected:* IGES (surfaces only, legacy), BREP (not an interchange format),
STL/3MF/glTF (meshes — a tessellated volume is approximate, disqualifying for a
tool that must not substitute values), FCStd (that is stage F).

**What it deliberately does not do.** A STEP file is baked geometry.
`parameter()` returns `None`, always — there is no `LENGTH_MM` in a STEP file —
and nothing can be written back parametrically.

**Addressing** is `path/to/file.step#NodeName`, or the whole file without a
fragment, in which case an assembly aggregates. A name matching two nodes raises
`Unsupported`; picking the first would be the same class of bug as substituting
a value.

**Built as an add-on.** `Build123dAdapter` was not touched, the mapping schema
did not change, and `make verify` produces byte-identical output. The cost is
that the measurement vocabulary now exists twice; `test_both_adapters_measure_
the_same` enforces the invariant instead of a refactor.

`python -m sysmlcad.explore_cad <file.step>` prints the assembly tree with the
reference strings to paste into the mapping — without it nobody can map a file
they did not author, because the node names are the addresses. It is also the
**catalogue of the CAD side** that stage H will need.

---

## Stage B — Change-impact analysis

5/5 user priority in the SRS (FREQ-8), a capability group on the slides, its
own scenario (SCN-3) — and it was missing from this roadmap entirely. It needs
no CAD write access: it is graph traversal over data already fetched, plus the
mapping. The fork's API supports it directly:

- `GET /projects/:p/commits/:c/elements/:id/relationships?direction=…`
- `GET /projects/:p/commits/:c/changes`

`impact.py`: given a change on either side, follow mapping entries and SysML
traceability links; return the affected requirements and verification cases,
**each with the link path that produced it**. Results derived from an
incomplete link structure are marked as such — the analysis can only be as
complete as the model it traverses.

Demo: the SRS's own example. Switching a housing from aluminium to plastic
looks local but touches the mass budget, the thermal path and the material
certification.

## Stage C — Evidence log and reports

Append-only SQLite: `run` (a `RunContext`) plus `result` (one row per evaluated
constraint). Nothing overwritten, nothing deleted — the history is the
traceability story. `report.py` produces HTML (human) and JSON (machine), both
stating which design state was checked against which requirement state.
JUnit XML stays for CI.

## Stage D — MCP server

A thin FastMCP wrapper over stages A–C: `list_requirements`, `verify`,
`analyze_impact`, `generate_report`, `explain_mapping`. No logic of its own.
This is the integration story from slides 8–9, and the point at which an
assistant can be asked "what breaks if this housing becomes plastic?" and get a
deterministic answer.

## Stage E — Gates and human confirmation

1. **Dimensional compatibility** — length↔length, mass↔mass, via pint
2. **Existence** — is the quantity measurable on the CAD object at all?
3. **Uniqueness** — no 1:n collisions
4. **Plausibility** — order of magnitude, e.g. a factor of 0.1–10
5. **Confirmation** — by a human, the first time round, recorded with user and
   timestamp (FREQ-5)

Result: *mapping valid / invalid*, reported separately from *pass / fail*.
Required before any write and before any AI proposal.

**One concrete hole to close here first.** The confirmation gate that already
exists covers `attributes:` only: `AttributeMapping.usable` demands
`status: confirmed`, but a `parts:` entry is used whatever its status says, and
that status is never validated on load. Setting the motorHousing part entry to
`status: proposed` still yields two verdicts. Small fix, but it is exactly the
FREQ-5 rule the rest of the design leans on, so it belongs at the front of this
stage rather than in a later cleanup.

## Stage F — FreeCAD adapter

**Narrowed by stage A2.** Everything measurable — geometry, assembly tree,
material where the exporter wrote one — the STEP adapter now covers, and for
every CAD system rather than only FreeCAD. Budget tracking, interface control
and substance compliance are reachable today through exported files.

What remains for FreeCAD is what a file fundamentally cannot carry:

- **named parameters** — the `LENGTH_MM` equivalent, in the document and its
  Spreadsheet, which is what FREQ-2 means by "named parameters maintained in
  skeleton objects and spreadsheets"
- **a live document** — reading a model the design engineer currently has open
- **parametric write-back** — the prerequisite for stage G's downward direction
  and for FREQ-6

`Build123dAdapter` stays regardless, so CI never needs FreeCAD installed.

## Stage G — Ownership-gated writes

The authority rule instead of a merge algorithm. The original plan proposed
Operational Transformation; that is over-engineering — OT solves
character-level concurrency in real-time editors, whereas model
synchronisation is a state-based three-way diff at low frequency. What
structurally prevents most conflicts is explicit ownership per parameter, which
is what FREQ-3's `direction` field already is.

- Writes only where the mapping entry grants authority: SysML owns limits, CAD
  owns actual values. Then the two sides cannot collide; all that remains are
  violations.
- **Up:** actual values and verdicts to SysML via `POST /projects/:id/commits`.
- **Down:** limits into CAD as parameters or annotations. **Never automatic
  geometry changes** — that creates traceability and signals that a change is
  needed without an algorithm silently rebuilding a part.
- Every run offers a dry-run preview of the value changes it would make
  (SRS §4.1, synchronisation view). Every write lands in the evidence log.

**FREQ-6 (structural instantiation)** — generating a CAD skeleton from the
SysML part structure — is deferred until this is stable. It is the most
expensive item in the SRS and buys the least until assemblies work.

**Read before designing this:** `Open-MBEE/sysmlv2_dls`, package `geometry_api`.
It has a CAD-agnostic assembly representation with translation, rotation and
ownership, plus an Onshape connector that writes out of SysML. Opposite design
decision to ours (there, SysML carries the geometry structure), but a finished
answer to the transformation maths if we move from single parts to assemblies.

## Stage H — AI mapping proposals

`rapidfuzz` (string distance) plus `sentence-transformers` (embeddings) over
names and metadata; optionally an LLM with structured JSON output. Candidates
enter with `status: proposed`, a confidence value and a rationale, and are
never applied automatically (FREQ-4, FREQ-5).

**Make it measurable:** hit rate against a hand-mapped gold set. Without that
number there is no evidence the AI part saves any time at all.

---

## Deferred, deliberately

**SMT over the constraint network.** A boundary the original plan was missing:
Z3 cannot prove anything about B-Rep geometry. SMT belongs on the *constraint
network*, not the CAD model. Sensible targets are consistency of the
requirement set, mass and cost budgets across assembly hierarchies, and
counterexamples in the parameter space — which become new test cases in the
verification engine automatically. Tool: `z3-solver`.

**Web frontend, OAuth2, multi-project dashboard.** In the SRS (§4.1, §4.3), not
in the next stages. The core is built as a library so the eventual UI is a
second consumer alongside the CLI and MCP, not a rewrite.

---

## Open architectural questions

**Which CAD system in production?** If CATIA or Creo is a given, the adapter
seam already accommodates it — the measurement core becomes an adapter over
their API instead of over OCC, and nothing above `CadAdapter` changes. The PoC
should then run against a slice of real model data early; that is where the
actual friction lives.

**Assemblies instead of single parts.** The measurement core knows one part per
object. Assemblies need aggregation (sum of masses) and positioning — see
Stage F and the `geometry_api` note above.

**Model management.** If versioning, branching and access control are needed
beyond the PoC, Open-MBEE (MMS) is the established candidate. At the current
stage it adds nothing over the pilot implementation.

**Contributing to the HNI fork.** `hibernate.hbm2ddl.auto` is the last
remaining gap in the fork's environment-variable concept; we patch it at clone
time. A PR adding `SYSML_HBM2DDL` alongside the existing `SYSML_JDBC_*`
variables would be small, cleanly scoped, and a natural reason to start a
conversation with the maintainers.
