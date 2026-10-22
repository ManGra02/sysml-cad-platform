import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"

import { cn } from "@/lib/utils"

import type { GateResult, GateVerdict, VerdictStatus } from "../queries"

// Small, shared pieces of the BDS pages: status pills, gate chips, dots.

const VERDICT_STYLE: Record<VerdictStatus, string> = {
  compliant: "bg-success/15 text-success",
  within_tolerance: "bg-warning/15 text-warning",
  violated: "bg-destructive/15 text-destructive",
}

export function VerdictPill({ status }: { status: VerdictStatus }) {
  const { t } = useTranslation()
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", VERDICT_STYLE[status])}>
      {t(`bds.verdict.${status}`)}
    </span>
  )
}

const GATE_STYLE: Record<GateVerdict, string> = {
  valid: "bg-success/15 text-success",
  unknown: "bg-warning/15 text-warning",
  invalid: "bg-destructive/15 text-destructive",
}
const GATE_MARK: Record<GateVerdict, string> = { valid: "✓", unknown: "?", invalid: "✗" }

/** One gate's answer, with its detail as the tooltip. */
export function GateChip({ result }: { result: GateResult }) {
  const { t } = useTranslation()
  return (
    <span title={result.detail} className={cn("rounded-md px-2 py-0.5 text-xs", GATE_STYLE[result.verdict])}>
      {GATE_MARK[result.verdict]} {t(`bds.gates.names.${result.gate}` as never, { defaultValue: result.gate })}
      {result.verdict !== "valid" && result.detail ? " · " + result.detail : ""}
    </span>
  )
}

/** The four gates as a compact row of dots. */
export function GateDots({ results }: { results: GateResult[] }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex gap-1" aria-label={results.map((r) => `${r.gate}: ${t(`bds.gates.verdict.${r.verdict}`)}`).join(", ")}>
      {results.map((result) => (
        <span
          key={result.gate}
          title={`${result.gate}: ${result.detail || t(`bds.gates.verdict.${result.verdict}`)}`}
          className={cn(
            "size-2.5 rounded-full",
            result.verdict === "valid" ? "bg-success" : result.verdict === "unknown" ? "bg-warning" : "bg-destructive",
          )}
        />
      ))}
    </span>
  )
}

export function GateVerdictBadge({ verdict, count }: { verdict: GateVerdict; count?: number }) {
  const { t } = useTranslation()
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs", GATE_STYLE[verdict])}>
      {count !== undefined ? `${count} ` : ""}
      {t(`bds.gates.verdict.${verdict}`)}
    </span>
  )
}

/** A tile with a big number, as on the SysML page. */
export function Tile({ label, value, hint, tone }: {
  label: string
  value: string | number
  hint?: string
  tone?: "success" | "warning" | "destructive"
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        tone === "success" && "border-success/30 bg-success/5",
        tone === "warning" && "border-warning/30 bg-warning/5",
        tone === "destructive" && "border-destructive/30 bg-destructive/5",
      )}
    >
      <div className="text-sm text-muted-foreground">{label}</div>
      <div
        className={cn(
          "text-2xl font-semibold tabular-nums",
          tone === "success" && "text-success",
          tone === "warning" && "text-warning",
          tone === "destructive" && "text-destructive",
        )}
      >
        {value}
      </div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">{children}</div>
}
