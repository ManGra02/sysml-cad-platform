import { Link } from "@tanstack/react-router"
import { ChevronDown } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { describeError } from "@/features/cad/format"
import { recomputeDocument, showInFreeCAD } from "@/features/cad/queries"
import { cn } from "@/lib/utils"

import type { WorkspaceActions } from "../actions"
import {
  assignState,
  checkState,
  crossCheck,
  describeMeasurement,
  gaugePosition,
  marginOf,
  previewFor,
  splitReference,
  type RequirementRow,
  type RowState,
} from "../logic"
import type { CadTarget, Catalog, Proposal, Requirement, Verdict, Workspace } from "../queries"
import { formatQuantity, formatValue, LimitText, Measurement, operatorSymbol, SanityCheck, StatePill } from "./bits"

/** What opening the measurement dialog needs: which attribute, for which requirement. */
export type MeasureRequest = {
  part: string
  attribute: string
  requirement?: Requirement
  /** Choosing another measurement for an existing entry. */
  replace?: RequirementRow["entry"]
}

export type TableContext = {
  workspace: Workspace
  catalog: Catalog
  targets: Map<string, CadTarget>
  actions: WorkspaceActions
  /** The stored result predates a change in FreeCAD or SysML. */
  stale: boolean
  checkedAt?: string
  onMeasure: (request: MeasureRequest) => void
  onTolerance: (row: RequirementRow) => void
  /** The one suggestion whose "Accept" is the page's primary action. */
  primaryProposal?: string
}

/**
 * "assign": which measurement belongs to the requirement, suggestions to decide.
 * "check": the measured value against the limit, and the result.
 */
export type TableMode = "assign" | "check"

const COLUMNS: Record<TableMode, string> = {
  assign: "md:grid md:grid-cols-[minmax(0,1fr)_8.5rem_13rem] md:gap-4",
  check: "md:grid md:grid-cols-[minmax(0,1fr)_8.5rem_14rem_14rem] md:gap-4",
}

/** One row per requirement -- a table on wide screens, cards on narrow ones. */
export function RequirementTable({ rows, context, mode }: { rows: RequirementRow[]; context: TableContext; mode: TableMode }) {
  const { t } = useTranslation()
  return (
    <section aria-label={t("bds.table.label")} className="overflow-hidden rounded-lg border bg-card">
      <div
        aria-hidden="true"
        className={cn("hidden border-b bg-muted/40 px-4 py-2 text-xs font-medium tracking-wide text-muted-foreground uppercase", COLUMNS[mode])}
      >
        <span>{t("bds.table.requirement")}</span>
        <span>{t("bds.table.limit")}</span>
        {mode === "check" && <span>{t("bds.table.value")}</span>}
        <span>{mode === "assign" ? t("bds.assign.column") : t("bds.check.column")}</span>
      </div>
      <ul className="divide-y">
        {rows.map((row) => (
          <RequirementRowView key={row.key} row={row} context={context} mode={mode} />
        ))}
      </ul>
    </section>
  )
}

function rowTone(state: RowState) {
  if (state === "violated") return "bg-destructive/5"
  if (state === "proposal" || state === "attributeUnclear") return "bg-warning/5"
  return ""
}

function RequirementRowView({ row, context, mode }: { row: RequirementRow; context: TableContext; mode: TableMode }) {
  const { t, i18n } = useTranslation()
  const state = mode === "assign" ? assignState(row) : checkState(row)
  const target = row.cadObject ? context.targets.get(row.cadObject) : undefined
  const objectName = target?.name ?? (row.cadObject ? splitReference(row.cadObject).name ?? row.cadObject : undefined)
  const showLabels = "md:hidden text-xs text-muted-foreground"

  return (
    <li className={cn("space-y-3 px-4 py-4 md:space-y-0", COLUMNS[mode], rowTone(state))}>
      {/* Requirement and how it is measured */}
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="font-semibold break-words">{row.id}</div>
            {row.requirement && row.requirement.text && row.requirement.text !== row.id && (
              <div className="text-sm text-muted-foreground">{row.requirement.text}</div>
            )}
          </div>
          <span className="md:hidden">
            <StatePill state={state} />
          </span>
        </div>
        <AssignmentLine row={row} context={context} target={target} objectName={objectName} readOnly={mode === "check"} />
        {mode === "assign" && row.proposals.length > 0 && <Proposals row={row} context={context} />}
      </div>

      {/* Limit */}
      <div className="text-sm">
        <span className={showLabels}>{t("bds.table.limit")}: </span>
        {row.requirement ? <LimitText requirement={row.requirement} tolerance={row.entry?.tolerance} /> : "–"}
      </div>

      {/* Value in FreeCAD */}
      {mode === "check" && (
        <div className="text-sm">
          <span className={showLabels}>{t("bds.table.value")}: </span>
          {row.verdict ? (
            <ValueCell verdict={row.verdict} stale={context.stale} checkedAt={context.checkedAt} />
          ) : (
            <span className="text-muted-foreground">–</span>
          )}
          {row.reason && row.state !== "notExtracted" && <p className="mt-1 text-xs text-muted-foreground">{row.reason}</p>}
          {row.state === "within_tolerance" && row.verdict?.tolerance && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("bds.limit.tolerance", { tolerance: formatQuantity(row.verdict.tolerance, i18n.language) })}
            </p>
          )}
        </div>
      )}

      {/* Status and what to do */}
      <div className="hidden space-y-2 md:block">
        <StatePill state={state} />
        {mode === "check" && <NotMeasuredNote row={row} context={context} />}
        <StatusAction row={row} state={state} mode={mode} context={context} />
      </div>
      <div className="space-y-2 md:hidden">
        {mode === "check" && <NotMeasuredNote row={row} context={context} />}
        <StatusAction row={row} state={state} mode={mode} context={context} />
      </div>
    </li>
  )
}

function AssignmentLine({ row, context, target, objectName, readOnly }: {
  row: RequirementRow
  context: TableContext
  target?: CadTarget
  objectName?: string
  /** "Check": how it is measured, without the means to change it. */
  readOnly?: boolean
}) {
  const { t } = useTranslation()
  const [chosen, setChosen] = useState<string>()
  const axes = context.workspace.axes

  if (row.state === "notExtracted") {
    return (
      <p className="text-sm text-muted-foreground">
        {row.reason}
        <span className="block text-xs">{t("bds.row.notExtractedHint")}</span>
      </p>
    )
  }

  const path = (
    <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
      {row.part}.{row.attribute || chosen || "?"}
    </code>
  )

  if (row.entry) {
    return (
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        {path}
        <span aria-hidden="true" className="text-muted-foreground">←</span>
        <Measurement method={row.entry.method} args={row.entry.args} axes={axes} target={target} objectName={objectName} attribute={row.attribute} />
        {row.state === "orphaned" ? (
          <span className="w-full text-xs text-muted-foreground">{t("bds.row.orphanedHint")}</span>
        ) : (
          !readOnly && <ChangeMenu row={row} context={context} />
        )}
      </div>
    )
  }

  if (row.state === "attributeUnclear" && !readOnly) {
    const part = context.catalog.sysml.find((p) => p.name === row.part)
    return (
      <div className="space-y-2 text-sm">
        <label className="block text-xs text-muted-foreground" htmlFor={"attr-" + row.key}>
          {t("bds.row.whichAttribute")}
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={chosen} onValueChange={setChosen}>
            <SelectTrigger id={"attr-" + row.key} size="sm" className="w-48">
              <SelectValue placeholder={t("bds.row.choose")} />
            </SelectTrigger>
            <SelectContent>
              {(part?.attributes ?? []).map((a) => (
                <SelectItem key={a.name} value={a.name}>
                  {row.part}.{a.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            disabled={!chosen}
            onClick={() => chosen && context.onMeasure({ part: row.part, attribute: chosen, requirement: row.requirement })}
          >
            {t("bds.row.chooseMeasurement")}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      {path}
      <span aria-hidden="true" className="text-muted-foreground">←</span>
      <span className="text-muted-foreground italic">{t("bds.row.noMeasurement")}</span>
    </div>
  )
}

function ChangeMenu({ row, context }: { row: RequirementRow; context: TableContext }) {
  const { t } = useTranslation()
  const entry = row.entry
  if (!entry) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 px-2 text-xs text-muted-foreground">
          {t("bds.row.change")} <ChevronDown className="size-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem
          onSelect={() => context.onMeasure({ part: row.part, attribute: row.attribute, requirement: row.requirement, replace: entry })}
        >
          {t("bds.row.changeMeasurement")}
        </DropdownMenuItem>
        {row.requirement && <DropdownMenuItem onSelect={() => context.onTolerance(row)}>{t("bds.row.changeTolerance")}</DropdownMenuItem>}
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => void context.actions.release(entry, row.cadObject)}>
          {t("bds.row.release")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ValueCell({ verdict, stale, checkedAt }: { verdict: Verdict; stale: boolean; checkedAt?: string }) {
  const { t, i18n } = useTranslation()
  const margin = marginOf(verdict)
  const gauge = gaugePosition(verdict.measured.value, verdict.limit.value)
  const amount = formatValue(margin.amount, margin.unit, i18n.language)
  const lower = verdict.operator === ">=" || verdict.operator === ">"
  const marginText =
    margin.amount === 0
      ? t("bds.row.atLimit")
      : margin.over
        ? lower
          ? t("bds.row.under", { amount })
          : t("bds.row.over", { amount })
        : t("bds.row.reserve", { amount })
  const tone = verdict.status === "violated" ? "bg-destructive" : verdict.status === "within_tolerance" ? "bg-warning" : "bg-success"
  return (
    <div className={cn(stale && "opacity-60")}>
      <div className="font-semibold tabular-nums">{formatQuantity(verdict.measured, i18n.language)}</div>
      <div className={cn("text-xs", margin.over ? "text-destructive" : "text-muted-foreground")}>{marginText}</div>
      <div aria-hidden="true" className="relative mt-2 h-1.5 w-40 max-w-full rounded-full bg-muted">
        <div className={cn("absolute inset-y-0 left-0 rounded-full", tone)} style={{ width: `${gauge.value * 100}%` }} />
        <div className="absolute -top-1 h-3.5 w-0.5 bg-foreground" style={{ left: `${gauge.limit * 100}%` }} />
      </div>
      {stale && checkedAt && (
        <div className="mt-1 text-xs text-muted-foreground">
          {t("bds.table.asOf", { time: new Date(checkedAt).toLocaleTimeString(i18n.language, { hour: "2-digit", minute: "2-digit" }) })}
        </div>
      )}
    </div>
  )
}

function StatusAction({ row, state, mode, context }: { row: RequirementRow; state: RowState; mode: TableMode; context: TableContext }) {
  const { t } = useTranslation()
  const document = context.workspace.cad_document
  const ref = row.cadObject ? splitReference(row.cadObject) : undefined

  const show = async () => {
    if (!ref?.name) return
    try {
      await showInFreeCAD(ref.doc, ref.name)
    } catch (error) {
      toast.error(describeError(error))
    }
  }
  const recompute = async () => {
    try {
      await recomputeDocument(ref?.doc ?? document)
      toast.success(t("bds.row.recomputed", { document: ref?.doc ?? document }))
      context.actions.changed()
    } catch (error) {
      toast.error(describeError(error))
    }
  }

  if (state === "unassigned" && mode === "check") {
    // Assigning happens under "Assign" -- "Check" only points there.
    return (
      <Button asChild size="sm" variant="outline">
        <Link to="/projects/bds/$ws/assign" params={{ ws: context.workspace.name }} search={(s) => s}>
          {t("bds.check.toAssign")}
        </Link>
      </Button>
    )
  }
  if (state === "unassigned") {
    return (
      <Button size="sm" variant="outline" onClick={() => context.onMeasure({ part: row.part, attribute: row.attribute, requirement: row.requirement })}>
        {t("bds.row.chooseMeasurement")}
      </Button>
    )
  }
  if (state === "notRecomputed") {
    return (
      <Button size="sm" variant="outline" onClick={() => void recompute()}>
        {t("bds.row.recompute")}
      </Button>
    )
  }
  if (state === "orphaned" && row.entry) {
    const entry = row.entry
    return (
      <Button size="sm" variant="outline" onClick={() => void context.actions.release(entry, row.cadObject)}>
        {t("bds.row.release")}
      </Button>
    )
  }
  if ((state === "violated" || state === "within_tolerance" || state === "compliant") && ref?.name) {
    return (
      <Button variant="link" size="sm" className="h-8 px-0" onClick={() => void show()}>
        {t("bds.row.showInFreecad")}
      </Button>
    )
  }
  return null
}

/** A value that is an entered number, not measured geometry -- said where the verdict is. */
function NotMeasuredNote({ row, context }: { row: RequirementRow; context: TableContext }) {
  const { t } = useTranslation()
  if (!row.entry || !row.verdict) return null
  const target = row.cadObject ? context.targets.get(row.cadObject) : undefined
  const { source } = describeMeasurement(row.entry.method, row.entry.args, context.workspace.axes, target)
  if (source === "geometry") return null
  return <p className="text-xs text-warning">{t("bds.row.notMeasured")}</p>
}

function Proposals({ row, context }: { row: RequirementRow; context: TableContext }) {
  const { t } = useTranslation()
  const [more, setMore] = useState(false)
  const [first, ...rest] = row.proposals
  return (
    <div className="space-y-2">
      <ProposalCard proposal={first} row={row} context={context} />
      {rest.length > 0 && (
        <>
          <Button variant="link" size="sm" className="h-8 px-0" aria-expanded={more} onClick={() => setMore(!more)}>
            {t("bds.proposal.more", { count: rest.length })}
          </Button>
          {more && rest.map((p) => <ProposalCard key={p.id} proposal={p} row={row} context={context} />)}
        </>
      )}
    </div>
  )
}

/**
 * A suggestion, made checkable: the value it would read, what the requirement would then
 * say, the object's own dimensions next to it, and a warning when the value is an entered
 * number rather than measured geometry. A wrong suggestion has to be visible BEFORE it is
 * accepted -- the gates cannot tell a thickness from a length of the same unit.
 */
export function ProposalCard({ proposal: p, row, context }: {
  proposal: Proposal
  row: Pick<RequirementRow, "id" | "part" | "attribute" | "requirement">
  context: TableContext
}) {
  const { t, i18n } = useTranslation()
  const [pending, setPending] = useState(false)
  const target = context.targets.get(p.cad_object)
  const axes = context.workspace.axes
  const { source } = describeMeasurement(p.method, p.args, axes, target)
  const measured = p.check?.measured ?? undefined
  const preview = row.requirement ? previewFor(p, row.id) : undefined
  const cross = measured && measured.unit === "mm" ? crossCheck(p.attribute, measured.value, target, axes, p.method) : undefined
  const blocked = p.check?.verdict === "invalid"
  const ai = p.proposed_by.startsWith("ai:")
  const size = target?.size ? target.size.map((v) => formatValue(v, "", i18n.language)).join(" × ") : undefined

  const run = async (action: () => Promise<void>) => {
    setPending(true)
    try {
      await action()
    } finally {
      setPending(false)
    }
  }

  return (
    <article className={cn("space-y-2 rounded-md border bg-background p-3 text-sm", cross && !cross.fits ? "border-warning" : "border-warning/40")}>
      <p className="text-xs font-medium text-muted-foreground">{ai ? t("bds.proposal.byAi") : t("bds.proposal.byName")}</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {/* In a requirement's row the path is already above the card. */}
        {!row.id && (
          <>
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
              {p.sysml_part}.{p.attribute}
            </code>
            <span aria-hidden="true" className="text-muted-foreground">←</span>
          </>
        )}
        <Measurement method={p.method} args={p.args} axes={axes} target={target} objectName={target?.name ?? p.cad_object} attribute={p.attribute} />
        {measured && <strong className="tabular-nums">= {formatQuantity(measured, i18n.language)}</strong>}
      </div>

      {preview ? (
        <p className={cn(preview.status === "compliant" ? "text-foreground" : "text-destructive")}>
          {t("bds.proposal.effect", {
            status: t(`bds.verdict.${preview.status}`),
            measured: formatQuantity(preview.measured, i18n.language),
            operator: operatorSymbol(preview.operator),
            limit: formatQuantity(preview.limit, i18n.language),
          })}
        </p>
      ) : (
        !measured && <p className="text-muted-foreground">{t("bds.proposal.noEffect")}</p>
      )}

      {cross && size && (
        <p className={cn("text-xs", cross.fits ? "text-muted-foreground" : "font-medium text-warning")}>
          {cross.fits
            ? t("bds.proposal.crossOk", { object: target?.name, size })
            : "⚠ " +
              t("bds.proposal.crossWarn", {
                object: target?.name,
                size,
                attribute: p.attribute,
                axis: cross.axis,
                expected: formatValue(cross.expected, "", i18n.language),
              })}
        </p>
      )}
      {source !== "geometry" && <p className="text-xs text-warning">{t("bds.proposal.enteredHint", { attribute: p.attribute })}</p>}
      {p.rationale && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{t("bds.proposal.why")}</summary>
          <p className="mt-1 italic">{p.rationale}</p>
        </details>
      )}
      {p.check && <SanityCheck gates={p.check.gates} />}
      {blocked && <p className="text-xs text-destructive">{t("bds.proposal.blocked")}</p>}

      <div className="flex flex-wrap gap-2 pt-1">
        <Button
          size="sm"
          variant={context.primaryProposal === p.id ? "default" : "outline"}
          disabled={pending || blocked}
          onClick={() => void run(() => context.actions.accept(p.id, row.requirement?.requirement, row.id))}
        >
          {t("bds.proposal.accept")}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={pending}
          onClick={() => context.onMeasure({ part: row.part, attribute: row.attribute || p.attribute, requirement: row.requirement })}
        >
          {t("bds.proposal.other")}
        </Button>
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => void run(() => context.actions.discard(p.id))}>
          {t("bds.proposal.discard")}
        </Button>
      </div>
    </article>
  )
}
