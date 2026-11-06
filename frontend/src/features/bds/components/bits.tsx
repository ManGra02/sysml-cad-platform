import { AlertTriangle, Check, CircleDashed, CircleHelp, Clock, X } from "lucide-react"
import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"

import { cn } from "@/lib/utils"

import { describeMeasurement, type MeasurementText, type RowState, type Source } from "../logic"
import type { CadTarget, GateResult, Quantity, Requirement } from "../queries"

// Small, shared pieces of the BDS areas: status pill, source tag, sanity check, numbers.

/** A number with its unit, in the reader's locale. */
export function formatValue(value: number, unit: string, language: string): string {
  const number = new Intl.NumberFormat(language, { maximumSignificantDigits: 4 }).format(value)
  return unit ? `${number} ${unit}` : number
}

export function formatQuantity(q: Quantity | null | undefined, language: string): string {
  return q ? formatValue(q.value, q.unit, language) : "–"
}

const OPERATOR: Record<string, string> = { "<=": "≤", ">=": "≥", "<": "<", ">": ">", "==": "=" }
export const operatorSymbol = (operator: string) => OPERATOR[operator] ?? operator

/** "≤ 95 mm" with the operator in words for screen readers and a tooltip. */
export function LimitText({ requirement, tolerance }: { requirement: Pick<Requirement, "operator" | "limit">; tolerance?: string | number | null }) {
  const { t, i18n } = useTranslation()
  const words = t(`bds.limit.${requirement.operator}` as never, { defaultValue: requirement.operator })
  return (
    <span className="tabular-nums" title={words}>
      <span aria-hidden="true">{operatorSymbol(requirement.operator)} </span>
      <span className="sr-only">{words} </span>
      {formatQuantity(requirement.limit, i18n.language)}
      {tolerance !== null && tolerance !== undefined && tolerance !== "" && (
        <span className="block text-xs text-muted-foreground">{t("bds.limit.tolerance", { tolerance: String(tolerance) })}</span>
      )}
    </span>
  )
}

type Tone = "success" | "warning" | "destructive" | "muted" | "info"

const STATE_TONE: Record<RowState, Tone> = {
  unassigned: "muted",
  attributeUnclear: "warning",
  proposal: "warning",
  assigned: "info",
  linked: "success",
  compliant: "success",
  within_tolerance: "warning",
  violated: "destructive",
  documentClosed: "muted",
  notRecomputed: "warning",
  notMeasurable: "warning",
  notExtracted: "muted",
  orphaned: "warning",
}

// Text stays in the foreground colour (4.5:1 on every tint); the colour is carried by the
// icon and the tint -- and the text says it anyway.
const TONE_STYLE: Record<Tone, string> = {
  success: "bg-success/15 text-foreground [&>svg]:text-success",
  warning: "bg-warning/15 text-foreground [&>svg]:text-warning",
  destructive: "bg-destructive/15 text-foreground [&>svg]:text-destructive",
  muted: "border border-dashed border-muted-foreground/50 text-muted-foreground",
  info: "bg-muted text-foreground",
}

function StateIcon({ state }: { state: RowState }) {
  const cls = "size-3.5 shrink-0"
  if (state === "compliant" || state === "linked") return <Check className={cls} aria-hidden="true" />
  if (state === "violated") return <X className={cls} aria-hidden="true" />
  if (state === "within_tolerance" || state === "notRecomputed" || state === "notMeasurable" || state === "orphaned")
    return <AlertTriangle className={cls} aria-hidden="true" />
  if (state === "assigned") return <Clock className={cls} aria-hidden="true" />
  if (state === "proposal" || state === "attributeUnclear") return <CircleHelp className={cls} aria-hidden="true" />
  return <CircleDashed className={cls} aria-hidden="true" />
}

/** The row's state: symbol AND text, never colour alone. */
export function StatePill({ state }: { state: RowState }) {
  const { t } = useTranslation()
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", TONE_STYLE[STATE_TONE[state]])}>
      <StateIcon state={state} />
      {t(`bds.state.${state}`)}
    </span>
  )
}

/** Where a value comes from: measured geometry, a spreadsheet's target value, an entered feature dimension. */
export function SourceTag({ source }: { source: Source }) {
  const { t } = useTranslation()
  return (
    <span
      title={t(`bds.source.${source}Hint`)}
      className={cn(
        "inline-flex rounded border px-1.5 text-[11px] leading-5 font-medium",
        source === "geometry" ? "border-border text-muted-foreground" : "border-warning/50 bg-warning/5 text-warning",
      )}
    >
      {t(`bds.source.${source}`)}
    </span>
  )
}

/** A measurement in words: "Extent in X (length)", "Bore radius · axis Z", "Table value Params.X". */
export function measurementWords(text: MeasurementText, t: (key: string, values?: Record<string, unknown>) => string): string {
  switch (text.kind) {
    case "bbox":
      return text.meaning
        ? t("bds.measure.bboxMeaning", { axis: text.axis, meaning: t(`bds.measure.meaning.${text.meaning}`) })
        : t("bds.measure.bbox", { axis: text.axis })
    case "radius": {
      const base = text.hole === undefined ? t("bds.measure.radius") : text.hole ? t("bds.measure.radiusHole") : t("bds.measure.radiusBoss")
      return text.axis ? `${base} · ${t("bds.measure.axis", { axis: text.axis })}` : base
    }
    case "sheet":
      return t("bds.measure.sheet", { name: text.name })
    case "feature":
      return t("bds.measure.feature", { name: text.name })
    case "mass":
      return t("bds.measure.mass")
    case "volume":
      return t("bds.measure.volume")
    case "faces":
      return t("bds.measure.faces")
    default:
      return t("bds.measure.other", { method: text.method })
  }
}

/** "Housing · Extent in X (length)" plus the source tag. */
export function Measurement({ method, args, axes, target, objectName, attribute }: {
  method: string
  args: Record<string, unknown> | null | undefined
  axes: Record<string, string>
  target?: CadTarget
  objectName?: string
  attribute?: string
}) {
  const { t } = useTranslation()
  const { text, source } = describeMeasurement(method, args, axes, target, attribute)
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-1">
      {objectName && <span className="font-medium">{objectName}</span>}
      {objectName && <span aria-hidden="true" className="text-muted-foreground">·</span>}
      <span title={text.kind === "mass" ? t("bds.measure.massHint") : undefined}>{measurementWords(text, t as never)}</span>
      <SourceTag source={source} />
    </span>
  )
}

const GATE_ICON = {
  valid: <Check className="size-3.5 text-success" aria-hidden="true" />,
  unknown: <AlertTriangle className="size-3.5 text-warning" aria-hidden="true" />,
  invalid: <X className="size-3.5 text-destructive" aria-hidden="true" />,
}

function ratioOf(gate: GateResult): string | undefined {
  const match = /measured\/limit = ([\d.e+-]+)/.exec(gate.detail)
  return match ? match[1] : undefined
}

/**
 * The gates in honest words: "Magnitude fits" -- never just "plausible" (the plausibility
 * gate only compares orders of magnitude). Compact: one line; ``detailed`` lists each check.
 */
export function SanityCheck({ gates: all, detailed = false }: { gates: GateResult[]; detailed?: boolean }) {
  const { t } = useTranslation()
  // Without a requirement there is no limit to compare the magnitude with -- not a problem.
  const gates = all.filter((g) => !(g.gate === "plausibility" && g.verdict === "unknown" && g.detail.startsWith("no measurement or no limit")))
  const worst = gates.some((g) => g.verdict === "invalid") ? "invalid" : gates.some((g) => g.verdict === "unknown") ? "unknown" : "valid"
  if (!detailed) {
    const label = worst === "valid" ? t("bds.sanity.ok") : worst === "invalid" ? t("bds.sanity.wrong") : t("bds.sanity.problem")
    const problems = gates.filter((g) => g.verdict !== "valid").map((g) => g.detail).filter(Boolean)
    return (
      <span
        className={cn("inline-flex items-center gap-1 text-xs", worst === "valid" ? "text-success" : worst === "invalid" ? "text-destructive" : "text-warning")}
        title={problems.join("\n") || undefined}
      >
        {GATE_ICON[worst]}
        {label}
      </span>
    )
  }
  return (
    <ul className="space-y-1 text-sm" aria-label={t("bds.sanity.label")}>
      {gates.map((gate) => {
        const ratio = gate.gate === "plausibility" ? ratioOf(gate) : undefined
        return (
          <li key={gate.gate} className="flex items-start gap-2">
            <span className="mt-0.5">{GATE_ICON[gate.verdict]}</span>
            <span>
              {t(`bds.sanity.gate.${gate.gate}` as never, { defaultValue: gate.gate })}
              {ratio && gate.verdict === "valid" && (
                <span className="text-muted-foreground"> ({t("bds.sanity.ratio", { ratio: Number(ratio).toPrecision(2) })})</span>
              )}
              {gate.verdict !== "valid" && gate.detail && <span className="block text-xs text-muted-foreground">{gate.detail}</span>}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">{children}</div>
}
