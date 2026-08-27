# Roadmap

*German original: [ROADMAP_de.md](ROADMAP_de.md).*

Guiding principle: get the thin end-to-end thread working first, then add
breadth. Every stage builds on a verified predecessor.

The target system is described in `goal_spec.txt` (SRS v0.1, "Bi-Directional
Synchronization") and the HNI/IEM use-case slides. This roadmap deviates from
both in a few places; where it does, the reason is written down.

| Stage | Content | Status |
|---|---|---|
| 0–3 | Infrastructure, extraction, measurement core, verification engine, CI | **done** |
| A | Re-anchor the mapping on parts; CAD adapter seam; three verdicts; provenance | **done** |
| B | Change-impact analysis | open |
| C | Evidence log and reports | open |
| D | MCP server | open |
| E | Gates and human confirmation | open |
| F | FreeCAD adapter | open |
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
  part-anchored mapping properly.
- Publish `airbus/apollo-11-sysml-v2` and run `explore.py` over it. Expect the
  "one comparison per requirement" assumption to break first. Cheap, hard
  evidence for which extractor simplification to fix next.

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

## Stage F — FreeCAD adapter

The second `CadAdapter`: document model, named parameters and Spreadsheet,
assembly tree, assigned materials. FREQ-2 describes a live CAD document, which
build123d structurally is not — it has no document, no assembly constraints and
no material property. FreeCAD is OCCT-based (matching SRS §4.2), free, and
scriptable headless.

Unlocks three of the four operational cases from the slides: budget tracking
(mass summed over an assembly), interface control (agreed dimension vs
as-designed), substance compliance (material and mass data).

`Build123dAdapter` stays, so CI never needs FreeCAD installed.

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
