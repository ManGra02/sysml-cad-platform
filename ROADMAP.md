# Roadmap

*German original: [ROADMAP_de.md](ROADMAP_de.md).*

Guiding principle: get the thin end-to-end thread working first, then add
breadth. Every phase builds on a verified predecessor.

| Phase | Content | Status |
|---|---|---|
| 0 | Infrastructure, reference example, naming conventions | **done** |
| 1 | Requirement extraction via the API | **done** |
| 2 | Measurement core on the B-Rep | **done** |
| 3 | Verification engine, report, CI | **done** |
| 4 | Mapping store, deterministic gates, AI hypotheses | open |
| 5 | Write-back, merge assistant | open |
| 6 | SMT over the constraint network | open |

---

## Phase 4 — Mapping (next step)

**The order is not negotiable: gates before AI.** Without gates there is no
yardstick to measure proposals against.

### 4.1 Mapping store

SQLite, replacing `mapping/mapping.yaml`. Minimum schema:

- `mapping`: `requirement_id`, `cad_module`, `method`, `args`, `property`,
  `status`, `author`, `created_at`
- `audit`: append-only; every status change with timestamp, author, and reason

`status ∈ {proposed, confirmed, rejected}`. Nothing is overwritten or deleted —
the history is part of the traceability story.

### 4.2 Deterministic gates

**The central conceptual point:** mapping validity and requirement satisfaction
are two different questions. The original project plan conflated them and wanted
to persist a mapping only if the requirement was satisfied. That is wrong:

- A correctly mapped part that is too long is a **violation**, not a bad mapping —
  and it is exactly the case the system is supposed to report.
- A wrong mapping that happens to satisfy the rule would be persisted.

Gates therefore check the *assignment* and nothing else:

1. **Dimensional compatibility** — length↔length, mass↔mass (via pint)
2. **Existence** — is the quantity measurable on the CAD object at all?
3. **Uniqueness** — no 1:n collisions
4. **Plausibility** — order of magnitude, e.g. a factor of 0.1–10 relative to the
   requirement
5. **Confirmation** — by a human, the first time round

Result: *mapping valid / invalid*. Separately from that, the existing
verification engine yields *pass / fail*.

### 4.3 AI hypotheses

`rapidfuzz` (string distance) plus `sentence-transformers` (embeddings) over the
names and metadata of SysML elements and CAD modules. Optionally an LLM with
structured JSON output.

**Make it measurable:** hit rate against a hand-mapped gold set. Without that
number, there is no way to tell whether the AI part saves any time at all.

### 4.4 First: put the extractor under load

Before phase 4 starts, publish the Airbus Apollo 11 model
(`airbus/apollo-11-sysml-v2`) and run `explore.py` over it. It is a deliberately
non-trivial SysML v2 model following the CoSMA framework. Expectation: the
"one comparison per requirement" assumption will be the first to break. Cheap,
hard evidence for which of the simplifications in `extract.py` need fixing first.

---

## Phase 5 — Reverse direction and conflicts

### 5.1 Write back, but metadata only

Changed limits from SysML land in the CAD script as an attribute or a comment.
**No automatic geometry changes.** This creates traceability and signals that a
change is needed, without an algorithm silently rebuilding a part.

### 5.2 An authority rule instead of a merge algorithm

The original project plan proposed Operational Transformation (OT). That is
over-engineering: OT solves character-level concurrency in real-time editors,
whereas model synchronisation is a state-based three-way diff at low frequency.

What structurally prevents 90% of conflicts is **explicit ownership per
parameter**: SysML owns limits (`maxLength`), CAD owns actual values
(`actualLength`). Then the two sides no longer collide — all that remains are
violations.

### 5.3 Merge assistant

A CLI diff over the mapping store, with three options per conflict (take SysML /
take CAD / resolve manually). The human decides, the system logs.

**Read before designing this:** `Open-MBEE/sysmlv2_dls`, package `geometry_api`.
It contains a CAD-agnostic assembly representation with translation, rotation,
and ownership, plus an Onshape connector that writes out of SysML. It takes the
opposite design decision to ours (there, SysML carries the geometry structure),
but it is a finished answer to the transformation maths, should we move from
single parts to assemblies.

---

## Phase 6 — Formal verification

**A boundary the original project plan was missing:** Z3 cannot prove anything
about B-Rep geometry. SMT belongs on the *constraint network*, not on the CAD
model.

Sensible targets:

- Consistency of the requirement set
- Mass and cost budgets across assembly hierarchies
- Counterexamples in the parameter space

Tool: `z3-solver`. Counterexamples it finds become new test cases in the
verification engine from phase 3 automatically.

---

## Open architectural questions

**Which CAD system in production?** If CATIA or Creo is a given, the measurement
core becomes an adapter layer over their API instead of over OCC. The
architecture stays the same, but the PoC should then run against a slice of real
model data early — that is where the actual friction lives.

**Assemblies instead of single parts.** So far the measurement core knows one
part per module. Assemblies need aggregation (sum of masses) and positioning —
see 5.3.

**Model management.** If versioning, branching, and access control are needed
beyond the PoC, Open-MBEE (MMS) is the established candidate. At the current
stage it adds nothing over the pilot implementation.

**Contributing to the HNI fork.** `hibernate.hbm2ddl.auto` is the last remaining
gap in the fork's environment-variable concept; we patch it at clone time. A PR
adding `SYSML_HBM2DDL` alongside the existing `SYSML_JDBC_*` variables would be
small, cleanly scoped, and a natural reason to start a conversation with the
maintainers.
