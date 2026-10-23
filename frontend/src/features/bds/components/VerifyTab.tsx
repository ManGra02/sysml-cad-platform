import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Play } from "lucide-react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { recomputeDocument, showInFreeCAD } from "@/features/cad/queries"
import { ApiError } from "@/lib/api"

import { cadRefOf, gapAction, gapRequirement, gaugePosition, runStaleness, type GapAction } from "../logic"
import { bdsKeys, lastRunQuery, runVerify, type Run, type Verdict } from "../queries"
import type { TabProps } from "../WorkspacePage"
import { EmptyNote, Tile, VerdictPill } from "./bits"

/** Run a verification; the result becomes the workspace's stored last run. */
export function useRunVerify(ws: string, commit?: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => runVerify(ws, { commit }),
    onSuccess: (run) => {
      queryClient.setQueryData(bdsKeys.lastRun(ws), run)
      void queryClient.invalidateQueries({ queryKey: bdsKeys.workspaces(), exact: true })
    },
    onError: (error) => toast.error(describeError(error)),
  })
}

/** The stored last run, or undefined when there is none yet (404 bds_no_run). */
export function useLastRun(ws: string) {
  const query = useQuery(lastRunQuery(ws))
  const none = query.error instanceof ApiError && query.error.code === "bds_no_run"
  return { ...query, run: query.data, none, failed: query.isError && !none }
}

export function VerifyTab({ workspace, commit, headCommit, cadChangedAt, onTab }: TabProps) {
  const { t, i18n } = useTranslation()
  const last = useLastRun(workspace.name)
  const verify = useRunVerify(workspace.name, commit)
  const run = last.run
  const stale = runStaleness(run, { headCommit, selectedCommit: commit, cadChangedAt })

  const button = (
    <Button onClick={() => verify.mutate()} disabled={verify.isPending}>
      <Play /> {verify.isPending ? t("bds.verify.running") : run ? t("bds.verify.again") : t("bds.verify.run")}
    </Button>
  )

  if (last.isPending) return <Skeleton className="h-40" />
  if (last.failed) return <p className="text-sm text-destructive">{describeError(last.error)}</p>
  if (!run) {
    return (
      <EmptyNote>
        <p className="mb-4">{t("bds.verify.none")}</p>
        {button}
      </EmptyNote>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">{t("bds.verify.hint")}</p>
        {button}
      </div>

      {stale && (
        <div role="status" className="rounded-md border border-blue-300 bg-blue-50 px-4 py-2 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100">
          {t(`bds.verify.stale.${stale}`)}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label={t("bds.verdict.compliant")} value={run.summary.compliant} tone="success" />
        <Tile label={t("bds.verdict.within_tolerance")} value={run.summary.within_tolerance} tone="warning" />
        <Tile label={t("bds.verdict.violated")} value={run.summary.violated} tone="destructive" />
        <Tile label={t("bds.verify.notChecked")} value={run.summary.not_checked} />
      </div>

      {run.verdicts.length > 0 && <VerdictTable verdicts={run.verdicts} />}

      {run.gaps.length > 0 && <GapList run={run} document={workspace.cad_document} onTab={onTab} />}

      <p className="text-xs text-muted-foreground">
        {t("bds.verify.provenance", {
          commit: run.context.sysml_commit_id.slice(0, 8) || "—",
          cad: run.context.cad_state_id || "—",
          mapping: run.context.mapping_digest,
          when: new Date(run.context.started_at).toLocaleString(i18n.language),
        })}
      </p>
    </div>
  )
}

function VerdictTable({ verdicts }: { verdicts: Verdict[] }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[52rem] text-sm">
        <thead className="bg-muted/50 text-left text-muted-foreground">
          <tr>
            <th className="px-4 py-2 font-medium">{t("bds.verify.columns.requirement")}</th>
            <th className="px-2 py-2 font-medium">{t("bds.verify.columns.attribute")}</th>
            <th className="px-2 py-2 font-medium">{t("bds.verify.columns.measured")}</th>
            <th className="px-2 py-2 font-medium">{t("bds.verify.columns.deviation")}</th>
            <th className="px-2 py-2 font-medium">{t("bds.verify.columns.status")}</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          {verdicts.map((v) => (
            <VerdictRow key={v.requirement + "@" + v.subject} verdict={v} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function VerdictRow({ verdict: v }: { verdict: Verdict }) {
  const { t } = useTranslation()
  const gauge = gaugePosition(v.measured.value, v.limit.value)
  const ref = cadRefOf(v.method)
  const show = async () => {
    if (!ref?.name) return
    try {
      await showInFreeCAD(ref.doc, ref.name)
    } catch (error) {
      toast.error(describeError(error))
    }
  }
  return (
    <tr className={v.status === "violated" ? "border-t bg-destructive/5" : "border-t"}>
      <td className="px-4 py-2 font-medium" title={v.text}>
        {v.requirement}
      </td>
      <td className="px-2 py-2">
        {v.subject}.{v.attribute}
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center gap-2">
          <span className="tabular-nums">
            {v.measured.text} {v.operator} {v.limit.text}
          </span>
          <span className="relative h-2 w-28 rounded-full bg-muted" aria-hidden="true">
            <span
              className={
                "absolute inset-y-0 left-0 rounded-full " +
                (v.status === "violated" ? "bg-destructive" : v.status === "within_tolerance" ? "bg-warning" : "bg-success")
              }
              style={{ width: `${gauge.value * 100}%` }}
            />
            <span className="absolute -top-1 h-4 w-0.5 bg-foreground" style={{ left: `${gauge.limit * 100}%` }} />
          </span>
        </div>
        {v.tolerance && <div className="text-xs text-muted-foreground">{t("bds.verify.tolerance", { tolerance: v.tolerance.text })}</div>}
      </td>
      <td className="px-2 py-2 tabular-nums">{v.deviation.value > 0 ? "+" + v.deviation.text : v.deviation.text}</td>
      <td className="px-2 py-2">
        <VerdictPill status={v.status} />
      </td>
      <td className="px-4 py-2 text-right text-xs">
        {ref?.name ? (
          <button type="button" className="underline" onClick={() => void show()}>
            {t("bds.verify.showInFreecad")}
          </button>
        ) : ref ? (
          <Link to="/cad/$doc" params={{ doc: ref.doc }} className="underline">
            {t("bds.verify.openExplorer")}
          </Link>
        ) : null}
      </td>
    </tr>
  )
}

function GapList({ run, document, onTab }: { run: Run; document: string; onTab: TabProps["onTab"] }) {
  const { t } = useTranslation()
  const recompute = async () => {
    try {
      await recomputeDocument(document)
      toast.success(t("bds.verify.recomputed", { document }))
    } catch (error) {
      toast.error(describeError(error))
    }
  }
  const actions: Record<GapAction, { label: string; run: () => void } | undefined> = {
    proposals: { label: t("bds.verify.gapActions.proposals"), run: () => onTab("proposals") },
    propose: { label: t("bds.verify.gapActions.propose"), run: () => onTab("proposals") },
    link: { label: t("bds.verify.gapActions.link"), run: () => onTab("mapping") },
    recompute: document ? { label: t("bds.verify.gapActions.recompute"), run: () => void recompute() } : undefined,
    openDocument: undefined,
    material: undefined,
    model: { label: t("bds.verify.gapActions.model"), run: () => onTab("catalog") },
    gates: { label: t("bds.verify.gapActions.gates"), run: () => onTab("mapping") },
  }
  return (
    <section className="space-y-2 rounded-lg border p-4">
      <h2 className="text-sm font-semibold">
        {t("bds.verify.gapsTitle", { count: run.gaps.length })}{" "}
        <span className="font-normal text-muted-foreground">{t("bds.verify.gapsHint")}</span>
      </h2>
      <ul className="divide-y text-sm">
        {run.gaps.map((gap, index) => {
          const kind = gapAction(gap)
          const action = kind ? actions[kind] : undefined
          const requirement = gapRequirement(gap)
          return (
            <li key={index} className="flex flex-wrap items-center gap-3 py-2">
              {requirement && <strong>{requirement}</strong>}
              <span className="min-w-0 flex-1 text-muted-foreground">
                {requirement ? gap.slice(requirement.length + 1).trim() : gap}
                {kind && !action && <span className="block text-xs">{t(`bds.verify.gapHints.${kind}`)}</span>}
              </span>
              {action && (
                <Button variant="outline" size="sm" onClick={action.run}>
                  {action.label}
                </Button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
