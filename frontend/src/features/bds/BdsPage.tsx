import { useQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowLeftRight, Plus } from "lucide-react"
import { useState } from "react"
import { Trans, useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { documentsQuery } from "@/features/cad/queries"
import { cn } from "@/lib/utils"

import { EmptyNote } from "./components/bits"
import { WorkspaceDialog } from "./components/WorkspaceDialog"
import { workspacesQuery, type Workspace } from "./queries"

// UI of the BDS group. Backend counterpart: backend/app/projects/bds/
// This page: every workspace (SysML project + FreeCAD document + mapping) as a card.
export function BdsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const workspaces = useQuery(workspacesQuery)
  const documents = useQuery({ ...documentsQuery, retry: false })
  const [creating, setCreating] = useState(false)
  const open = documents.data ? new Set(documents.data.documents.map((d) => d.name)) : undefined

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-start gap-4">
        <div className="grid size-12 shrink-0 place-items-center rounded-lg bg-muted">
          <ArrowLeftRight className="size-6" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold">{t("bds.list.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("bds.list.hint")}</p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus /> {t("bds.list.new")}
        </Button>
      </div>

      {workspaces.isPending && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      )}
      {workspaces.isError && <p className="text-sm text-destructive">{describeError(workspaces.error)}</p>}
      {workspaces.data && workspaces.data.length === 0 && (
        <EmptyNote>
          <p className="mb-2">{t("bds.list.empty")}</p>
          <p>
            <Trans i18nKey="bds.list.emptyModels" components={{ code: <code className="rounded bg-muted px-1.5 py-0.5 text-xs" /> }} />
          </p>
        </EmptyNote>
      )}
      {workspaces.data && workspaces.data.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {workspaces.data.map((workspace) => (
            <WorkspaceCard
              key={workspace.name}
              workspace={workspace}
              documentOpen={open && workspace.cad_document ? open.has(workspace.cad_document) : undefined}
            />
          ))}
        </div>
      )}

      <p className="rounded-md border border-dashed px-4 py-3 text-xs text-muted-foreground">
        <Trans i18nKey="bds.list.storage" components={{ code: <code className="rounded bg-muted px-1 py-0.5" /> }} />
      </p>

      {creating && (
        <WorkspaceDialog
          open={creating}
          onOpenChange={setCreating}
          onSaved={(saved) => void navigate({ to: "/projects/bds/$ws", params: { ws: saved.name } })}
        />
      )}
    </div>
  )
}

function WorkspaceCard({ workspace: w, documentOpen }: { workspace: Workspace; documentOpen?: boolean }) {
  const { t, i18n } = useTranslation()
  const run = w.last_run
  const ran = run ? run.summary.compliant + run.summary.within_tolerance + run.summary.violated + run.summary.not_checked : 0

  return (
    <Link
      to="/projects/bds/$ws"
      params={{ ws: w.name }}
      className="flex flex-col gap-3 rounded-lg border p-5 transition-colors hover:bg-accent/50"
    >
      <div className="flex items-center gap-2">
        <span className="truncate font-semibold">{w.name}</span>
        <span
          className={cn(
            "ml-auto shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
            !run && "bg-muted text-muted-foreground",
            run && run.violated && "bg-destructive/15 text-destructive",
            run && !run.violated && "bg-success/15 text-success",
          )}
        >
          {!run
            ? t("bds.list.notVerified")
            : run.violated
              ? t("bds.list.violated", { count: run.summary.violated })
              : t("bds.list.satisfied", { ok: run.summary.compliant + run.summary.within_tolerance, total: ran })}
        </span>
      </div>
      <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">{t("bds.list.sysml")}</dt>
        <dd className="truncate">{w.sysml_project}</dd>
        <dt className="text-muted-foreground">{t("bds.list.freecad")}</dt>
        <dd className="truncate">
          {w.cad_document || "—"}
          {documentOpen === true && <span className="text-success"> · {t("bds.list.open")}</span>}
          {documentOpen === false && <span className="text-warning"> · {t("bds.list.notOpen")}</span>}
        </dd>
        <dt className="text-muted-foreground">{t("bds.list.mapping")}</dt>
        <dd>
          {w.counts.attributes_confirmed === null
            ? t("bds.list.mappingBroken")
            : w.counts.attributes_confirmed
              ? t("bds.list.mappingCounts", { parts: w.counts.parts_confirmed, attributes: w.counts.attributes_confirmed })
              : t("bds.list.mappingEmpty")}
        </dd>
      </dl>
      <div className="mt-auto flex flex-wrap items-center gap-2 text-xs">
        {w.counts.proposals_pending > 0 && (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 text-warning">
            {t("bds.list.pending", { count: w.counts.proposals_pending })}
          </span>
        )}
        {run && run.summary.not_checked > 0 && (
          <span className="rounded-full bg-muted px-2 py-0.5">{t("bds.list.gaps", { count: run.summary.not_checked })}</span>
        )}
        {run && (
          <span className="ml-auto text-muted-foreground">
            {t("bds.list.checkedAt", { when: new Date(run.context.started_at).toLocaleString(i18n.language) })}
          </span>
        )}
      </div>
    </Link>
  )
}
