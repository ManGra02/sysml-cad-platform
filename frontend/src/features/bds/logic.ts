import type {
  AttributeMapping,
  CadTarget,
  Catalog,
  Mapping,
  Proposal,
  ProposalPreview,
  Requirement,
  Run,
  Verdict,
} from "./queries"

// Pure helpers of the BDS pages -- everything here is unit-tested (logic.test.ts).
// One row per requirement, walking unassigned -> proposal -> assigned -> verdict;
// requirementRows() decides where each row stands, assignState()/checkState() what the
// "Assign" and "Check" areas show of it.

/** Last segment of a qualified name: MotorHousing::motorHousing -> motorHousing. */
export function leaf(name: string): string {
  const index = name.lastIndexOf("::")
  return index < 0 ? name : name.slice(index + 2)
}

function words(name: string): string[] {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_\-.#:]+/g, " ")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
}

/** "boreRadius" -> "radius": the word an axis convention or a parameter name is matched on. */
export function lastWord(name: string): string | undefined {
  return words(name).at(-1)
}

export function requirementsOf(requirements: Requirement[], part: string): Requirement[] {
  return requirements.filter((r) => leaf(r.subject) === part)
}

/** The requirement id a gap sentence is about ("MaxLength: ..."), if it starts with one. */
export function gapRequirement(gap: string): string | undefined {
  const match = /^([A-Za-z_][\w]*):/.exec(gap)
  return match?.[1]
}

// -- Rows -----------------------------------------------------------------------

export type RowState =
  | "unassigned"
  | "attributeUnclear"
  | "proposal"
  | "assigned"
  | "linked"
  | "compliant"
  | "within_tolerance"
  | "violated"
  | "documentClosed"
  | "notRecomputed"
  | "notMeasurable"
  | "notExtracted"
  | "orphaned"

export type RequirementRow = {
  key: string
  /** The requirement id -- also for rows the model no longer (or never readably) states. */
  id: string
  requirement?: Requirement
  part: string
  /** The constrained attribute: the mapping entry's, else what the extractor read, else "". */
  attribute: string
  entry?: AttributeMapping
  cadObject?: string
  /** Pending proposals for part.attribute, best first. */
  proposals: Proposal[]
  verdict?: Verdict
  /** Why it is not measurable / not extracted -- the backend's sentence. */
  reason?: string
  state: RowState
}

export type RowInput = {
  catalog: Pick<Catalog, "requirements" | "not_extracted">
  mapping?: Mapping
  proposals?: Proposal[]
  run?: Run
  /** false: the workspace's FreeCAD document is known to be closed. */
  documentOpen?: boolean
}

const usable = (e: AttributeMapping) => e.status === "confirmed"

function pendingFor(proposals: Proposal[] | undefined, part: string, attribute: string): Proposal[] {
  if (!attribute) return []
  return (proposals ?? [])
    .filter((p) => p.status === "proposed" && p.sysml_part === part && p.attribute === attribute)
    .sort((a, b) => b.confidence - a.confidence)
}

function gapState(gap: string): RowState {
  if (gap.includes("recompute in FreeCAD") || gap.includes("marks it invalid")) return "notRecomputed"
  if (gap.includes("is not open")) return "documentClosed"
  return "notMeasurable"
}

export function requirementRows({ catalog, mapping, proposals, run, documentOpen }: RowInput): RequirementRow[] {
  const entries = (mapping?.attributes ?? []).filter((e) => e.status !== "disabled")
  const rows: RequirementRow[] = []

  for (const requirement of catalog.requirements) {
    const part = leaf(requirement.subject)
    const id = requirement.requirement
    const matching = entries.filter((e) => e.requirement === id && e.sysml_part === part)
    const entry = matching.find(usable) ?? matching[0]
    const attribute = entry?.attribute ?? requirement.attribute
    const row: RequirementRow = {
      key: id + "@" + part,
      id,
      requirement,
      part,
      attribute,
      entry,
      cadObject: entry ? mapping?.parts.find((p) => p.sysml_part === part)?.cad_object : undefined,
      proposals: entry ? [] : pendingFor(proposals, part, attribute),
      state: "unassigned",
    }
    if (!entry) {
      row.state = row.proposals.length ? "proposal" : attribute ? "unassigned" : "attributeUnclear"
    } else {
      const verdict = run?.verdicts.find((v) => v.requirement === id && leaf(v.subject) === part)
      const gap = run?.gaps.find((g) => gapRequirement(g) === id)
      if (documentOpen === false) {
        row.state = "documentClosed"
      } else if (verdict) {
        row.verdict = verdict
        row.state = verdict.status
      } else if (gap) {
        row.state = gapState(gap)
        row.reason = gap.slice(id.length + 1).trim()
      } else {
        row.state = "assigned"
      }
    }
    rows.push(row)
  }

  // Requirements the extractor could not read stay in the table -- "not checked" must show.
  for (const reason of catalog.not_extracted) {
    const id = gapRequirement(reason) ?? reason
    rows.push({ key: "x:" + id, id, part: "", attribute: "", proposals: [], state: "notExtracted",
      reason: reason.slice(id.length + 1).trim() })
  }

  // Entries checking a requirement the model no longer states.
  const known = new Set(catalog.requirements.map((r) => r.requirement + "@" + leaf(r.subject)))
  const unreadable = new Set(catalog.not_extracted.map((r) => gapRequirement(r)))
  for (const entry of entries) {
    if (!usable(entry) || !entry.requirement || unreadable.has(entry.requirement)) continue
    if (known.has(entry.requirement + "@" + entry.sysml_part)) continue
    rows.push({ key: "o:" + entry.requirement + "@" + entry.sysml_part, id: entry.requirement, part: entry.sysml_part,
      attribute: entry.attribute, entry, proposals: [], state: "orphaned",
      cadObject: mapping?.parts.find((p) => p.sysml_part === entry.sysml_part)?.cad_object })
  }
  return rows
}

export type Assignment = {
  entry: AttributeMapping
  cadObject?: string
  /** The one requirement this entry evidently checks -- linked automatically. */
  linkable?: Requirement
}

/** Confirmed entries no requirement uses: shown apart, "not checked". */
export function otherAssignments(mapping: Mapping | undefined, requirements: Requirement[]): Assignment[] {
  const entries = (mapping?.attributes ?? []).filter((e) => usable(e) && !e.requirement)
  const linked = new Set((mapping?.attributes ?? []).filter((e) => e.requirement).map((e) => e.requirement + "@" + e.sysml_part))
  return entries.map((entry) => {
    const candidates = requirementsOf(requirements, entry.sysml_part).filter(
      (r) => r.attribute === entry.attribute && !linked.has(r.requirement + "@" + entry.sysml_part),
    )
    return {
      entry,
      cadObject: mapping?.parts.find((p) => p.sysml_part === entry.sysml_part)?.cad_object,
      linkable: candidates.length === 1 ? candidates[0] : undefined,
    }
  })
}

/** Pending proposals for attributes no requirement constrains. */
export function otherProposals(proposals: Proposal[] | undefined, rows: RequirementRow[]): Proposal[] {
  const covered = new Set(rows.map((r) => r.part + "." + r.attribute))
  return (proposals ?? []).filter((p) => p.status === "proposed" && !covered.has(p.sysml_part + "." + p.attribute))
}

export type Progress = {
  total: number
  assigned: number
  checked: number
  passed: number
  tolerance: number
  violated: number
  open: number
  /** Assigned after the last check: no verdict and no gap yet. */
  unchecked: number
  /** Assigned, but the last check could not measure them. */
  unmeasured: number
}

export function progress(rows: RequirementRow[]): Progress {
  const real = rows.filter((r) => r.state !== "orphaned")
  const assigned = real.filter((r) => r.entry).length
  const count = (state: RowState) => real.filter((r) => r.state === state).length
  const passed = count("compliant")
  const tolerance = count("within_tolerance")
  const violated = count("violated")
  return { total: real.length, assigned, checked: passed + tolerance + violated, passed, tolerance, violated,
    open: real.length - assigned, unchecked: count("assigned"),
    unmeasured: count("notMeasurable") + count("notRecomputed") + count("documentClosed") }
}

/**
 * What the overview points to next -- one step, in the order the work is done: decide
 * the waiting suggestions, assign, check (again), look at violations, finish assigning.
 */
export type NextStep =
  | { kind: "empty" | "start" | "offline" | "closed" | "check" | "recheck" | "done"; count?: undefined }
  | { kind: "review" | "violated" | "unmeasured" | "rest"; count: number }

export function nextStep(p: Progress, pendingProposals: number,
  checked: { run: boolean; stale: boolean; bridgeDown?: boolean; documentOpen?: boolean }): NextStep {
  if (p.total === 0) return { kind: "empty" }
  if (pendingProposals > 0) return { kind: "review", count: pendingProposals }
  if (p.assigned === 0) return { kind: "start" }
  // Nothing can be measured -- that is the next thing to fix, in FreeCAD.
  if (checked.bridgeDown) return { kind: "offline" }
  if (checked.documentOpen === false) return { kind: "closed" }
  if (!checked.run) return { kind: "check" }
  // An assignment newer than the result counts as a change, too.
  if (checked.stale || p.unchecked > 0) return { kind: "recheck" }
  if (p.violated > 0) return { kind: "violated", count: p.violated }
  if (p.unmeasured > 0) return { kind: "unmeasured", count: p.unmeasured }
  if (p.open > 0) return { kind: "rest", count: p.open }
  return { kind: "done" }
}

/** "Assign": where a row stands in finding its measurement -- results do not matter there. */
export function assignState(row: Pick<RequirementRow, "entry" | "state">): RowState {
  if (!row.entry || row.state === "orphaned") return row.state
  return "linked"
}

/** "Check": a row without a measurement is simply not assigned yet -- deciding is the other area's job. */
export function checkState(row: Pick<RequirementRow, "state">): RowState {
  return row.state === "proposal" || row.state === "attributeUnclear" ? "unassigned" : row.state
}

/** The first suggestion on the page -- the one primary "Accept"; every other is secondary. */
export function firstProposalId(rows: RequirementRow[]): string | undefined {
  return rows.find((r) => r.proposals.length > 0)?.proposals[0].id
}

// -- Measurements in words ----------------------------------------------------------

export type Source = "geometry" | "sheet" | "feature"

const MEANINGS = ["length", "width", "height", "thickness"]

export type MeasurementText =
  | { kind: "bbox"; axis: string; meaning?: string }
  | { kind: "radius"; hole?: boolean; axis?: string }
  | { kind: "sheet" | "feature"; name: string }
  | { kind: "mass" | "volume" | "faces" }
  | { kind: "other"; method: string }

/** A measurement as words (the component translates them) and where its value comes from. */
export function describeMeasurement(method: string, args: Record<string, unknown> | null | undefined,
  axes: Record<string, string>, target?: Pick<CadTarget, "sheet_parameters">, attribute?: string): { text: MeasurementText; source: Source } {
  const a = args ?? {}
  if (method === "bbox_size") {
    const axis = String(a.axis ?? "X").toUpperCase()
    // The attribute's own word when the convention puts it on this axis (thickness on Z),
    // else what the axis means for a box.
    const own = attribute ? lastWord(attribute) : undefined
    const meaning = own && MEANINGS.includes(own) && axes[own] === axis ? own : ["length", "width", "height"].find((name) => axes[name] === axis)
    return { text: { kind: "bbox", axis, meaning }, source: "geometry" }
  }
  if (method === "cylinder_radius") {
    return { text: { kind: "radius", hole: a.kind === undefined ? undefined : a.kind === "hole",
      axis: a.axis ? String(a.axis).toUpperCase() : undefined }, source: "geometry" }
  }
  if (method === "parameter") {
    const name = String(a.name ?? "")
    const sheet = target?.sheet_parameters.includes(name) ?? false
    return { text: { kind: sheet ? "sheet" : "feature", name }, source: sheet ? "sheet" : "feature" }
  }
  if (method === "mass") return { text: { kind: "mass" }, source: "geometry" }
  if (method === "volume") return { text: { kind: "volume" }, source: "geometry" }
  if (method === "face_count") return { text: { kind: "faces" }, source: "geometry" }
  return { text: { kind: "other", method }, source: "geometry" }
}

const LENGTH_UNITS = new Set(["mm", "cm", "m", "in", "ft", "µm", "um"])
const MASS_UNITS = new Set(["kg", "g", "t", "lb"])

/** "8 mm" -> its dimension, as the catalogue spells it. */
export function dimensionOf(text: string): string | undefined {
  const unit = text.trim().split(/\s+/).slice(1).join(" ")
  if (LENGTH_UNITS.has(unit)) return "[length]"
  if (MASS_UNITS.has(unit)) return "[mass]"
  if (/^(mm|cm|m)(\^|\*\*)3$|^(mm|cm|m)³$/.test(unit)) return "[length] ** 3"
  return undefined
}

export type MeasurementOption = {
  method: string
  args: Record<string, unknown>
  source: Source
  /** The value as the catalogue already knows it -- the dry run gives the exact one. */
  value?: string
}

const fmt = (n: number) => String(Math.round(n * 1000) / 1000)

/** What an object offers for an attribute of this dimension (undefined: anything). */
export function measurementOptions(target: CadTarget, dimension: string | null | undefined): MeasurementOption[] {
  const out: MeasurementOption[] = []
  const wants = (d: string) => !dimension || dimension === d
  const offers = (m: string) => target.methods.includes(m)
  if (wants("[length]")) {
    if (offers("bbox_size")) {
      ;(["X", "Y", "Z"] as const).forEach((axis, i) => out.push({ method: "bbox_size", args: { axis }, source: "geometry",
        value: target.size ? fmt(target.size[i]) + " mm" : undefined }))
    }
    if (offers("cylinder_radius")) {
      for (const c of target.cylinders) {
        const args: Record<string, unknown> = { kind: c.kind }
        if (c.axis) args.axis = c.axis
        if (!out.some((o) => o.method === "cylinder_radius" && JSON.stringify(o.args) === JSON.stringify(args))) {
          out.push({ method: "cylinder_radius", args, source: "geometry", value: fmt(c.radius) + " mm" })
        }
      }
    }
  }
  if (wants("[mass]") && offers("mass")) out.push({ method: "mass", args: {}, source: "geometry", value: target.mass?.text })
  if (wants("[length] ** 3") && offers("volume")) out.push({ method: "volume", args: {}, source: "geometry" })
  if (!dimension && offers("face_count")) out.push({ method: "face_count", args: {}, source: "geometry" })
  if (offers("parameter")) {
    const names = Object.keys(target.parameters).sort((a, b) =>
      Number(!target.sheet_parameters.includes(a)) - Number(!target.sheet_parameters.includes(b)) || a.localeCompare(b))
    for (const name of names) {
      const value = target.parameters[name]
      if (dimension && dimensionOf(value) !== dimension) continue
      out.push({ method: "parameter", args: { name }, source: target.sheet_parameters.includes(name) ? "sheet" : "feature", value })
    }
  }
  return out
}

export type CrossCheck = { axis: string; expected: number; fits: boolean }

/**
 * Does a length value fit the object's extent along the axis the workspace's convention
 * names for the attribute? Catches "Pad001.Length (6 mm) as cover.length" -- a length
 * that is really the thickness. undefined: nothing to compare against.
 */
export function crossCheck(attribute: string, measured: number | undefined, target: Pick<CadTarget, "size"> | undefined,
  axes: Record<string, string>, method: string): CrossCheck | undefined {
  if (measured === undefined || !target?.size || (method !== "bbox_size" && method !== "parameter")) return undefined
  const word = lastWord(attribute)
  const axis = word ? axes[word] : undefined
  if (!axis) return undefined
  const expected = target.size["XYZ".indexOf(axis)]
  if (expected === undefined) return undefined
  return { axis, expected, fits: Math.abs(measured - expected) <= Math.max(1e-6, Math.abs(expected) * 1e-3) }
}

/** The preview of a proposal for one requirement (from GET proposals?check=true). */
export function previewFor(proposal: Proposal, requirement: string): ProposalPreview | undefined {
  return proposal.previews?.find((p) => p.requirement === requirement)
}

// -- Numbers ----------------------------------------------------------------------

/**
 * Where a value sits on a fixed scale: the limit always at 80 %, the scale up to 1.25 x
 * the limit -- so bars of different requirements read alike.
 */
export function gaugePosition(measured: number, limit: number): { value: number; limit: number } {
  if (!limit) return { value: measured ? 1 : 0, limit: 0.8 }
  return { value: Math.max(0, Math.min(1, (measured / limit) * 0.8)), limit: 0.8 }
}

export type Margin = { over: boolean; amount: number; unit: string }

/** How far from the limit, in the direction that matters: over it, or the reserve left. */
export function marginOf(v: Pick<Verdict, "operator" | "deviation">): Margin {
  const d = v.deviation.value
  const upper = v.operator === "<=" || v.operator === "<"
  const lower = v.operator === ">=" || v.operator === ">"
  const over = upper ? d > 0 : lower ? d < 0 : d !== 0
  return { over, amount: Math.abs(d), unit: v.deviation.unit }
}

export type Staleness = "commit" | "cad" | undefined

/**
 * Is a stored verification result still about the current state? Only says so -- a new
 * run is the user's call (it reads FreeCAD and Flexo).
 */
export function runStaleness(run: Pick<Run, "context"> | undefined, current: {
  headCommit?: string
  selectedCommit?: string
  cadChangedAt?: number
}): Staleness {
  if (!run) return undefined
  const expected = current.selectedCommit ?? current.headCommit
  if (expected && run.context.sysml_commit_id && expected !== run.context.sysml_commit_id) return "commit"
  const started = Date.parse(run.context.started_at)
  if (current.cadChangedAt !== undefined && !Number.isNaN(started) && current.cadChangedAt > started) return "cad"
  return undefined
}

/** The CAD object a verdict was measured on, from its method text "... on freecad:Doc#Name". */
export function cadRefOf(method: string): { doc: string; name?: string } | undefined {
  const match = / on [\w-]+:([^#\s]+)(?:#(\S+))?$/.exec(method)
  if (!match) return undefined
  return match[2] ? { doc: match[1], name: match[2] } : { doc: match[1] }
}

/** "Doc#Name" -> parts for showInFreeCAD; a bare document name has no object. */
export function splitReference(reference: string): { doc: string; name?: string } {
  const [doc, name] = reference.split("#")
  return name ? { doc, name } : { doc }
}
