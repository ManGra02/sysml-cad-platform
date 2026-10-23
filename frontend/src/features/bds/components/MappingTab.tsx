import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react"
import { Fragment, useState } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { cn } from "@/lib/utils"

import { describeMethod } from "../logic"
import { gatesQuery, mappingQuery, type AttributeMapping, type GateCheck } from "../queries"
import type { TabProps } from "../WorkspacePage"
import { EmptyNote, GateDots, GateVerdictBadge } from "./bits"

/** The mapping with each entry's gate answers: is the ASSIGNMENT sound (not the design)? */
export function MappingTab({ workspace, commit, onTab }: TabProps) {
  const { t } = useTranslation()
  const mapping = useQuery(mappingQuery(workspace.name))
  const gates = useQuery(gatesQuery(workspace.name, commit))
  const [open, setOpen] = useState<string>()

  if (mapping.isPending) return <Skeleton className="h-40" />
  if (mapping.isError) return <p className="text-sm text-destructive">{describeError(mapping.error)}</p>
  if (mapping.data.attributes.length === 0) {
    return (
      <EmptyNote>
        <p className="mb-4">{t("bds.mapping.empty")}</p>
        <Button onClick={() => onTab("proposals")}>{t("bds.mapping.toProposals")}</Button>
      </EmptyNote>
    )
  }

  const checks = new Map((gates.data?.entries ?? []).map((c) => [c.sysml_part + "." + c.attribute, c]))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm">{t("bds.mapping.hint")}</p>
          <p className="text-xs text-muted-foreground">
            {t("bds.mapping.file", { name: workspace.name, digest: mapping.data.digest })}
          </p>
        </div>
        {gates.data && (
          <span className="flex gap-1.5">
            {(["valid", "unknown", "invalid"] as const).map((v) => (
              <GateVerdictBadge key={v} verdict={v} count={gates.data.summary[v] ?? 0} />
            ))}
          </span>
        )}
        <Button variant="outline" size="sm" disabled={gates.isFetching} onClick={() => void gates.refetch()}>
          <RefreshCw className={cn(gates.isFetching && "animate-spin")} /> {t("bds.mapping.recheck")}
        </Button>
      </div>
      {gates.isError && <p className="text-sm text-destructive">{describeError(gates.error)}</p>}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[56rem] text-sm">
          <thead className="bg-muted/50 text-left text-muted-foreground">
            <tr>
              <th className="w-8" />
              <th className="px-2 py-2 font-medium">{t("bds.mapping.columns.attribute")}</th>
              <th className="px-2 py-2 font-medium">{t("bds.mapping.columns.cadObject")}</th>
              <th className="px-2 py-2 font-medium">{t("bds.mapping.columns.measurement")}</th>
              <th className="px-2 py-2 font-medium">{t("bds.mapping.columns.requirement")}</th>
              <th className="px-2 py-2 font-medium">{t("bds.mapping.columns.measured")}</th>
              <th className="px-2 py-2 font-medium">{t("bds.mapping.columns.gates")}</th>
              <th className="px-4 py-2 font-medium">{t("bds.mapping.columns.origin")}</th>
            </tr>
          </thead>
          <tbody>
            {mapping.data.attributes.map((entry) => {
              const key = entry.sysml_part + "." + entry.attribute
              const part = mapping.data.parts.find((p) => p.sysml_part === entry.sysml_part)
              return (
                <MappingRow
                  key={key + entry.status}
                  entry={entry}
                  cadObject={part?.cad_object}
                  check={entry.status === "disabled" ? undefined : checks.get(key)}
                  loading={gates.isPending}
                  open={open === key}
                  onToggle={() => setOpen(open === key ? undefined : key)}
                />
              )
            })}
          </tbody>
        </table>
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">{t("bds.mapping.parts")}</h2>
        <div className="flex flex-wrap gap-2 text-sm">
          {mapping.data.parts.map((part) => (
            <span
              key={part.sysml_part}
              className={cn("rounded-md border px-2.5 py-1.5", part.status !== "confirmed" && "border-warning/40 bg-warning/5")}
            >
              {part.sysml_part} → <code>{part.cad_object}</code>{" "}
              <span className={part.status === "confirmed" ? "text-success" : "text-warning"}>
                {t(`bds.mapping.partStatus.${part.status}`)}
              </span>
            </span>
          ))}
        </div>
        {gates.data && gates.data.unused_parts.length > 0 && (
          <p className="text-xs text-muted-foreground">{t("bds.mapping.unused", { parts: gates.data.unused_parts.join(", ") })}</p>
        )}
      </section>
    </div>
  )
}

function MappingRow({ entry, cadObject, check, loading, open, onToggle }: {
  entry: AttributeMapping
  cadObject?: string
  check?: GateCheck
  loading: boolean
  open: boolean
  onToggle: () => void
}) {
  const { t } = useTranslation()
  const problem = check && check.verdict !== "valid"
  return (
    <Fragment>
      <tr
        className={cn(
          "border-t",
          check?.verdict === "unknown" && "bg-warning/5",
          check?.verdict === "invalid" && "bg-destructive/5",
          entry.status !== "confirmed" && "text-muted-foreground",
        )}
      >
        <td className="pl-2">
          {check && (
            <button type="button" onClick={onToggle} aria-expanded={open} aria-label={t("bds.mapping.details")}>
              {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            </button>
          )}
        </td>
        <td className="px-2 py-2 font-medium">
          {entry.sysml_part}.{entry.attribute}
          {entry.status !== "confirmed" && (
            <span className="ml-2 rounded bg-muted px-1.5 text-xs font-normal">{t(`bds.mapping.partStatus.${entry.status}`)}</span>
          )}
        </td>
        <td className="px-2 py-2">
          <code>{cadObject ?? "—"}</code>
        </td>
        <td className="px-2 py-2">{describeMethod(entry.method, entry.args)}</td>
        <td className={cn("px-2 py-2", !entry.requirement && "text-warning")}>
          {entry.requirement || t("bds.mapping.noRequirement")}
        </td>
        <td className="px-2 py-2 tabular-nums">{check?.measured?.text ?? "—"}</td>
        <td className="px-2 py-2">
          {check ? <GateDots results={check.gates} /> : loading ? <Skeleton className="h-3 w-14" /> : "—"}
        </td>
        <td className="px-4 py-2 text-xs text-muted-foreground">
          {entry.author || t("bds.mapping.manual")}
          {entry.confirmed_at ? " · " + entry.confirmed_at : ""}
        </td>
      </tr>
      {open && check && (
        <tr className={cn(problem && "bg-warning/5")}>
          <td />
          <td colSpan={7} className="px-2 pb-3">
            <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
              {check.gates.map((gate) => (
                <div
                  key={gate.gate}
                  className={cn(
                    "rounded-md border bg-background p-2",
                    gate.verdict === "unknown" && "border-warning/50",
                    gate.verdict === "invalid" && "border-destructive/50",
                  )}
                >
                  <strong className={gate.verdict === "valid" ? "text-success" : gate.verdict === "unknown" ? "text-warning" : "text-destructive"}>
                    {t(`bds.gates.names.${gate.gate}` as never, { defaultValue: gate.gate })} · {t(`bds.gates.verdict.${gate.verdict}`)}
                  </strong>
                  {gate.detail && <p className="mt-1 text-muted-foreground">{gate.detail}</p>}
                </div>
              ))}
            </div>
            {entry.note && <p className="mt-2 text-xs text-muted-foreground">{entry.note}</p>}
          </td>
        </tr>
      )}
    </Fragment>
  )
}
