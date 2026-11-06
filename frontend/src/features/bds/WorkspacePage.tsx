import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { documentsQuery, statusQuery } from "@/features/cad/queries"
import { sysmlCommitsQuery } from "@/features/sysml/queries"
import { ApiError } from "@/lib/api"
import { TitleScope, useDocumentTitle } from "@/lib/useDocumentTitle"
import { eventSocket } from "@/lib/ws"

import { useWorkspaceActions } from "./actions"
import { ToleranceDialog } from "./components/Dialogs"
import { MeasurementDialog } from "./components/MeasurementDialog"
import type { MeasureRequest, TableContext } from "./components/RequirementTable"
import { WorkspaceHeader, WorkspaceTabs } from "./components/Sections"
import { WorkspaceDialog } from "./components/WorkspaceDialog"
import { WorkspaceContext, type WorkspaceData } from "./context"
import {
  firstProposalId,
  otherAssignments,
  otherProposals,
  progress,
  requirementRows,
  runStaleness,
  type RequirementRow,
} from "./logic"
import {
  bdsKeys,
  catalogQuery,
  invalidateMapping,
  lastRunQuery,
  mappingQuery,
  proposalsQuery,
  updateEntry,
  workspacesQuery,
  type ProposeResult,
  type Run,
  type Workspace,
} from "./queries"

const CAD_CHANGES = new Set(["cad.changed", "cad.created", "cad.deleted", "cad.recomputed", "cad.history", "cad.resync"])

/**
 * Live updates for one workspace. A FreeCAD change to its document only MARKS results as
 * outdated (re-reading costs a round through FreeCAD and Flexo); a finished check -- from
 * this page or another -- refreshes the stored result.
 */
function useBdsFrames(workspace: Workspace | undefined) {
  const queryClient = useQueryClient()
  const [cadChangedAt, setCadChangedAt] = useState<number>()
  const name = workspace?.name
  const doc = workspace?.cad_document

  useEffect(
    () =>
      eventSocket.onFrame((frame) => {
        if (frame.type === "events" && doc) {
          const events = (frame.events as Array<{ type: string; doc?: string }> | undefined) ?? []
          if (events.some((e) => CAD_CHANGES.has(e.type) && (e.doc === undefined || e.doc === doc))) {
            setCadChangedAt(Date.now())
          }
        }
        if (frame.type === "bds.verify.done" && (frame.data as { workspace?: string } | undefined)?.workspace === name) {
          void queryClient.invalidateQueries({ queryKey: bdsKeys.lastRun(name ?? "") })
          void queryClient.invalidateQueries({ queryKey: bdsKeys.workspaces(), exact: true })
        }
      }),
    [queryClient, name, doc],
  )
  return cadChangedAt
}

/**
 * One workspace: header, the area tabs (overview, assign, check, limits, models) and the
 * area itself as `children` (the route's outlet). The data is read here, once, and handed
 * to the areas through WorkspaceContext.
 */
export function WorkspacePage({ ws, commit, onCommit, children }: {
  ws: string
  commit?: string
  onCommit: (commit?: string) => void
  children: ReactNode
}) {
  const { t } = useTranslation()
  useDocumentTitle(ws, t("bds.list.title"))
  const workspaces = useQuery(workspacesQuery)
  const workspace = workspaces.data?.find((w) => w.name === ws)

  if (workspaces.isPending) return <Skeleton className="m-6 h-40" />
  if (workspaces.isError) return <p className="p-6 text-sm text-destructive">{describeError(workspaces.error)}</p>
  if (!workspace) {
    return (
      <div className="p-10 text-center text-sm text-muted-foreground">
        {t("bds.page.notFound", { name: ws })}{" "}
        <Link to="/projects/bds" className="underline">
          {t("bds.page.toList")}
        </Link>
      </div>
    )
  }
  return (
    <WorkspaceLayout workspace={workspace} commit={commit} onCommit={onCommit}>
      {children}
    </WorkspaceLayout>
  )
}

function WorkspaceLayout({ workspace, commit, onCommit, children }: {
  workspace: Workspace
  commit?: string
  onCommit: (commit?: string) => void
  children: ReactNode
}) {
  const { t } = useTranslation()
  const ws = workspace.name
  const catalog = useQuery(catalogQuery(ws, commit))
  const mapping = useQuery(mappingQuery(ws))
  const proposals = useQuery(proposalsQuery(ws, commit, true))
  const last = useQuery(lastRunQuery(ws))
  const commits = useQuery(sysmlCommitsQuery(workspace.sysml_project))
  const documents = useQuery({ ...documentsQuery, retry: false })
  const status = useQuery(statusQuery)
  const cadChangedAt = useBdsFrames(workspace)
  const [announcement, setAnnouncement] = useState("")
  const [measure, setMeasure] = useState<MeasureRequest>()
  const [tolerance, setTolerance] = useState<RequirementRow>()
  const [editing, setEditing] = useState(false)
  const [lastProposal, setLastProposal] = useState<ProposeResult>()

  const onChecked = (run: Run) => {
    const s = run.summary
    setAnnouncement(t("bds.live.checked", { passed: s.compliant, tolerance: s.within_tolerance, violated: s.violated, open: s.not_checked }))
  }
  const actions = useWorkspaceActions(ws, commit, onChecked)

  const run = last.data
  const noRun = last.error instanceof ApiError && last.error.code === "bds_no_run"
  // Unknown while the bridge is not connected: "closed" is only said when FreeCAD says so.
  const documentOpen = workspace.cad_document && documents.data
    ? documents.data.documents.some((d) => d.name === workspace.cad_document)
    : undefined
  const bridge = status.data?.bridge.state
  const bridgeDown = status.isError || (bridge !== undefined && bridge !== "ok" && bridge !== "busy")
  const headCommit = commits.data?.[0]?.id
  const stale = runStaleness(run, { headCommit, selectedCommit: commit, cadChangedAt })

  const rows = useMemo(
    () => (catalog.data ? requirementRows({ catalog: catalog.data, mapping: mapping.data, proposals: proposals.data, run, documentOpen }) : []),
    [catalog.data, mapping.data, proposals.data, run, documentOpen],
  )
  const others = useMemo(() => otherAssignments(mapping.data, catalog.data?.requirements ?? []), [mapping.data, catalog.data])
  const strayProposals = useMemo(() => otherProposals(proposals.data, rows), [proposals.data, rows])
  const targets = useMemo(() => new Map((catalog.data?.cad ?? []).map((x) => [x.reference, x])), [catalog.data])

  useAutoLink(ws, others, actions.changed)

  const table: TableContext = {
    workspace,
    catalog: catalog.data!,
    targets,
    actions,
    // Values from an earlier state: FreeCAD changed since, or FreeCAD cannot be asked.
    stale: !!stale || bridgeDown,
    checkedAt: run?.context.started_at,
    primaryProposal: firstProposalId(rows),
    onMeasure: setMeasure,
    onTolerance: setTolerance,
  }
  const data: WorkspaceData | undefined = catalog.data && {
    workspace,
    commit,
    catalog: catalog.data,
    mapping: mapping.data,
    run,
    runError: last.isError && !noRun ? last.error : undefined,
    rows,
    progress: progress(rows),
    pending: rows.reduce((n, r) => n + r.proposals.length, 0),
    others,
    strayProposals,
    rejected: (proposals.data ?? []).filter((p) => p.status === "rejected"),
    lastProposal,
    setLastProposal,
    table,
    actions,
    bridgeDown,
    documentOpen,
    stale,
    cadChangedAt,
    onMeasure: setMeasure,
  }

  return (
    <div>
      <WorkspaceHeader
        workspace={workspace}
        commits={commits.data ?? []}
        commit={commit}
        onCommit={onCommit}
        onSettings={() => setEditing(true)}
      >
        {data && <WorkspaceTabs data={data} />}
      </WorkspaceHeader>

      <div className="mx-auto max-w-6xl space-y-4 px-4 py-5 sm:px-6">
        <p aria-live="polite" className="sr-only">
          {announcement}
        </p>
        {commit && (
          <p className="flex flex-wrap items-center gap-3 rounded-md border border-blue-300 bg-blue-50 px-4 py-2 text-sm text-blue-950 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-50">
            <span className="flex-1">{t("bds.banner.older", { id: commit.slice(0, 8) })}</span>
            <Button size="sm" variant="outline" onClick={() => onCommit(undefined)}>
              {t("bds.banner.toLatest")}
            </Button>
          </p>
        )}

        {catalog.isPending ? (
          <Skeleton className="h-64" />
        ) : catalog.isError ? (
          <p className="text-sm text-destructive">{describeError(catalog.error)}</p>
        ) : (
          data && (
            <WorkspaceContext.Provider value={data}>
              <TitleScope>{children}</TitleScope>
            </WorkspaceContext.Provider>
          )
        )}
      </div>

      {measure && catalog.data && (
        <MeasurementDialog
          request={measure}
          workspace={workspace}
          commit={commit}
          catalog={catalog.data}
          mapping={mapping.data}
          actions={actions}
          onClose={() => setMeasure(undefined)}
        />
      )}
      {tolerance && <ToleranceDialog row={tolerance} workspace={workspace} actions={actions} onClose={() => setTolerance(undefined)} />}
      {editing && <WorkspaceDialog open={editing} onOpenChange={setEditing} existing={workspace} />}
    </div>
  )
}

/**
 * Old assignments without a requirement, where exactly one requirement of the part
 * constrains that attribute: linked once, automatically, with a notice. Everything
 * ambiguous stays under "other assignments" for a person to decide.
 */
function useAutoLink(ws: string, others: ReturnType<typeof otherAssignments>, changed: () => void) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const done = useRef<string>(undefined)
  const linkable = others.filter((a) => a.linkable)
  useEffect(() => {
    if (linkable.length === 0 || done.current === ws) return
    done.current = ws
    void (async () => {
      let count = 0
      for (const a of linkable) {
        try {
          await updateEntry(ws, a.entry, { requirement: a.linkable!.requirement })
          count += 1
        } catch {
          // stays under "other assignments" with its own button
        }
      }
      if (count) {
        toast.info(t("bds.banner.linked", { count }))
        changed()
      } else {
        invalidateMapping(queryClient, ws)
      }
    })()
  }, [ws, linkable, changed, t, queryClient])
}
