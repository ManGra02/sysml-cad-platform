import type { GateCheck, Mapping, Proposal, Requirement, Run, Workspace } from "./queries"

// Pure helpers of the BDS pages -- everything here is unit-tested (logic.test.ts).

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

export function requirementsOf(requirements: Requirement[], part: string): Requirement[] {
  return requirements.filter((r) => leaf(r.subject) === part)
}

/**
 * The requirement a confirmation is pre-filled with -- a suggestion the reviewer sees and
 * can change, never a decision: the one requirement on the part whose name says the
 * attribute (MaxHousingLength for housing.length). Being the part's only requirement is
 * not enough: MaxCoverThickness says nothing about cover.length.
 */
export function defaultRequirement(requirements: Requirement[], part: string, attribute: string): string | undefined {
  const own = requirementsOf(requirements, part)
  const last = words(attribute).at(-1)
  const named = own.filter((r) => last !== undefined && words(r.requirement).includes(last))
  return named.length === 1 ? named[0].requirement : undefined
}

export type AttributeState =
  | { state: "confirmed"; requirement: string }
  | { state: "proposed"; proposal: string }
  | { state: "disabled" }
  | { state: "open" }

/** Where one SysML attribute stands: mapped, waiting for a decision, or not covered at all. */
export function attributeState(mapping: Mapping | undefined, proposals: Proposal[] | undefined, part: string,
  attribute: string): AttributeState {
  const entries = (mapping?.attributes ?? []).filter((a) => a.sysml_part === part && a.attribute === attribute)
  const confirmed = entries.find((a) => a.status === "confirmed")
  if (confirmed) return { state: "confirmed", requirement: confirmed.requirement }
  const pending = (proposals ?? []).find((p) => p.status === "proposed" && p.sysml_part === part && p.attribute === attribute)
  if (pending) return { state: "proposed", proposal: pending.id }
  if (entries.some((a) => a.status === "disabled")) return { state: "disabled" }
  return { state: "open" }
}

export type GapAction = "proposals" | "propose" | "link" | "recompute" | "openDocument" | "material" | "model" | "gates"

/**
 * What to do about a gap -- read from the backend's sentence (verify.py, bridge_adapter.py).
 * Unknown wording gets no button rather than a wrong one.
 */
export function gapAction(gap: string): GapAction | undefined {
  if (gap.includes("without a requirement")) return "link"
  if (gap.includes("not confirmed")) return "proposals"
  if (gap.includes("no mapping entry")) return "propose"
  if (gap.includes("recompute in FreeCAD")) return "recompute"
  if (gap.includes("is not open")) return "openDocument"
  if (gap.includes("no material with a density")) return "material"
  if (gap.includes("not extracted")) return "model"
  if (gap.includes("a mapping fault")) return "gates"
  return undefined
}

/** The requirement id a gap is about ("MaxLength: ..."), if it starts with one. */
export function gapRequirement(gap: string): string | undefined {
  const match = /^([A-Za-z_][\w]*):/.exec(gap)
  return match?.[1]
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

export type NextStep =
  | { kind: "openDocument"; document: string }
  | { kind: "propose" }
  | { kind: "review"; count: number }
  | { kind: "verify" }
  | { kind: "fix"; count: number }
  | { kind: "sync" }

/** The overview's "next steps", in the order the workflow goes. */
export function nextSteps(workspace: Workspace, documentOpen: boolean | undefined): NextStep[] {
  const steps: NextStep[] = []
  if (workspace.cad_document && documentOpen === false) steps.push({ kind: "openDocument", document: workspace.cad_document })
  if (!workspace.counts.attributes_confirmed && !workspace.counts.proposals_pending) steps.push({ kind: "propose" })
  if (workspace.counts.proposals_pending) steps.push({ kind: "review", count: workspace.counts.proposals_pending })
  if (!workspace.last_run) {
    if (workspace.counts.attributes_confirmed) steps.push({ kind: "verify" })
  } else {
    const open = workspace.last_run.summary.violated + workspace.last_run.summary.not_checked
    if (open) steps.push({ kind: "fix", count: open })
  }
  if (workspace.counts.attributes_confirmed) steps.push({ kind: "sync" })
  return steps
}

export function gateCounts(checks: GateCheck[]): Record<"valid" | "unknown" | "invalid", number> {
  const out = { valid: 0, unknown: 0, invalid: 0 }
  for (const check of checks) out[check.verdict] += 1
  return out
}

/** "bbox_size · X", "cylinder_radius · hole", "parameter · Params.Length". */
export function describeMethod(method: string, args: Record<string, unknown> | null | undefined): string {
  const values = Object.values(args ?? {}).filter((v) => v !== null && v !== undefined)
  return values.length ? method + " · " + values.map(String).join(", ") : method
}

/** Where a measured value sits relative to its limit, 0..1 on a scale up to 1.25 x limit. */
export function gaugePosition(measured: number, limit: number): { value: number; limit: number } {
  const top = Math.max(Math.abs(limit), Math.abs(measured)) * 1.25 || 1
  return { value: Math.min(1, Math.abs(measured) / top), limit: Math.min(1, Math.abs(limit) / top) }
}

/** The CAD object a verdict was measured on, from its method text "... on freecad:Doc#Name". */
export function cadRefOf(method: string): { doc: string; name?: string } | undefined {
  const match = / on [\w-]+:([^#\s]+)(?:#(\S+))?$/.exec(method)
  if (!match) return undefined
  return match[2] ? { doc: match[1], name: match[2] } : { doc: match[1] }
}
