import { useQuery } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { aiStatusQuery } from "@/features/ai/queries"
import { documentsQuery } from "@/features/cad/queries"
import { sysmlStatusQuery } from "@/features/sysml/queries"
import { cn } from "@/lib/utils"

import { nextSteps, runStaleness, type NextStep } from "../logic"
import { catalogQuery } from "../queries"
import type { TabProps, WorkspaceTab } from "../WorkspacePage"
import { Tile } from "./bits"
import { useLastRun, useRunVerify } from "./VerifyTab"

/** Where the workspace stands, and what to do next. */
export function OverviewTab({ workspace, commit, headCommit, cadChangedAt, onTab }: TabProps) {
  const { t, i18n } = useTranslation()
  const catalog = useQuery(catalogQuery(workspace.name, commit))
  const documents = useQuery({ ...documentsQuery, retry: false })
  const sysml = useQuery(sysmlStatusQuery)
  const ai = useQuery(aiStatusQuery)
  const last = useLastRun(workspace.name)
  const verify = useRunVerify(workspace.name, commit)
  const run = last.run
  const documentOpen = documents.data
    ? documents.data.documents.some((d) => d.name === workspace.cad_document)
    : documents.isError
      ? false
      : undefined
  const stale = runStaleness(run, { headCommit, selectedCommit: commit, cadChangedAt })
  const steps = nextSteps(workspace, documentOpen)

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label={t("bds.overview.requirements")}
          value={catalog.data?.requirements.length ?? "–"}
          hint={
            catalog.data
              ? catalog.data.not_extracted.length
                ? t("bds.overview.notExtracted", { count: catalog.data.not_extracted.length })
                : t("bds.overview.allExtracted")
              : undefined
          }
        />
        <Tile
          label={t("bds.overview.mapping")}
          value={workspace.counts.attributes_confirmed ?? "!"}
          hint={t("bds.overview.mappingHint", { parts: workspace.counts.parts_confirmed ?? 0 })}
        />
        <Tile
          label={t("bds.overview.lastRun")}
          value={run ? `${run.summary.compliant + run.summary.within_tolerance} / ${run.verdicts.length + run.gaps.length}` : "–"}
          hint={
            run
              ? t("bds.overview.lastRunHint", {
                  violated: run.summary.violated,
                  gaps: run.summary.not_checked,
                  when: new Date(run.context.started_at).toLocaleString(i18n.language),
                }) + (stale ? " · " + t("bds.overview.stale") : "")
              : t("bds.overview.neverRun")
          }
          tone={run ? (run.violated ? "destructive" : "success") : undefined}
        />
        <Tile
          label={t("bds.overview.pending")}
          value={workspace.counts.proposals_pending}
          tone={workspace.counts.proposals_pending ? "warning" : undefined}
        />
      </div>

      <div className="flex flex-wrap gap-5">
        <section className="min-w-0 flex-[2_1_28rem] space-y-3 rounded-lg border p-5">
          <h2 className="font-semibold">{t("bds.overview.nextSteps")}</h2>
          {steps.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("bds.overview.allDone")}</p>
          ) : (
            <ol className="space-y-2 text-sm">
              {steps.map((step) => (
                <StepItem key={step.kind} step={step} onTab={onTab} onVerify={() => verify.mutate()} verifying={verify.isPending} />
              ))}
            </ol>
          )}
        </section>

        <section className="min-w-0 flex-[1_1_16rem] space-y-2 rounded-lg border p-5 text-sm">
          <h2 className="font-semibold">{t("bds.overview.connections")}</h2>
          <Connection ok={sysml.data?.reachable} label={t("bds.overview.flexo", { project: workspace.sysml_project })} />
          <Connection
            ok={documentOpen}
            label={
              workspace.cad_document
                ? t(documentOpen === false ? "bds.overview.documentClosed" : "bds.overview.document", { document: workspace.cad_document })
                : t("bds.overview.noDocument")
            }
          />
          <Connection
            ok={ai.data ? ai.data.configured && !!ai.data.projects.bds?.model : undefined}
            label={t("bds.overview.ai", { model: ai.data?.projects.bds?.model ?? "—" })}
          />
          <p className="pt-1 text-xs text-muted-foreground">
            {t("bds.overview.settings", {
              length: workspace.axes.length,
              width: workspace.axes.width,
              height: workspace.axes.height,
              sheet: workspace.limits_sheet,
            })}
          </p>
        </section>
      </div>
    </div>
  )
}

function Connection({ ok, label }: { ok?: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn("size-2 shrink-0 rounded-full", ok === undefined ? "bg-muted-foreground/40" : ok ? "bg-success" : "bg-warning")}
      />
      {label}
    </div>
  )
}

const STEP_TAB: Partial<Record<NextStep["kind"], WorkspaceTab>> = {
  propose: "proposals",
  review: "proposals",
  fix: "verify",
  sync: "sync",
}

function StepItem({ step, onTab, onVerify, verifying }: {
  step: NextStep
  onTab: (tab: WorkspaceTab) => void
  onVerify: () => void
  verifying: boolean
}) {
  const { t } = useTranslation()
  const tab = STEP_TAB[step.kind]
  const text =
    step.kind === "openDocument"
      ? t("bds.overview.steps.openDocument", { document: step.document })
      : step.kind === "review" || step.kind === "fix"
        ? t(`bds.overview.steps.${step.kind}`, { count: step.count })
        : t(`bds.overview.steps.${step.kind}`)
  return (
    <li className="flex flex-wrap items-center gap-3">
      <span className="font-semibold text-warning">!</span>
      <span className="min-w-0 flex-1">{text}</span>
      {step.kind === "verify" ? (
        <Button size="sm" disabled={verifying} onClick={onVerify}>
          {t("bds.verify.run")}
        </Button>
      ) : tab ? (
        <Button size="sm" variant="outline" onClick={() => onTab(tab)}>
          {t(`bds.tabs.${tab}`)}
        </Button>
      ) : null}
    </li>
  )
}
