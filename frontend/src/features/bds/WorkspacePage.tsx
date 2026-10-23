import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Settings } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { describeError } from "@/features/cad/format"
import { sysmlCommitsQuery } from "@/features/sysml/queries"
import { useDocumentTitle } from "@/lib/useDocumentTitle"
import { eventSocket } from "@/lib/ws"

import { CatalogTab } from "./components/CatalogTab"
import { MappingTab } from "./components/MappingTab"
import { OverviewTab } from "./components/OverviewTab"
import { ProposalsTab } from "./components/ProposalsTab"
import { SyncTab } from "./components/SyncTab"
import { VerifyTab } from "./components/VerifyTab"
import { WorkspaceDialog } from "./components/WorkspaceDialog"
import { bdsKeys, workspacesQuery, type Workspace } from "./queries"

export const WORKSPACE_TABS = ["overview", "catalog", "proposals", "mapping", "verify", "sync"] as const
export type WorkspaceTab = (typeof WORKSPACE_TABS)[number]

/** What every tab gets: the workspace, the model state, and how to move between tabs. */
export type TabProps = {
  workspace: Workspace
  commit?: string
  headCommit?: string
  cadChangedAt?: number
  onTab: (tab: WorkspaceTab) => void
}

const CAD_CHANGES = new Set(["cad.changed", "cad.created", "cad.deleted", "cad.recomputed", "cad.history", "cad.resync"])

/**
 * Live updates for one workspace. A FreeCAD change to its document only MARKS results as
 * outdated (re-reading the catalogue costs a round through FreeCAD and Flexo); a finished
 * verification -- from this tab or another -- refreshes the stored result.
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

export function WorkspacePage({ ws, tab, commit, onTab, onCommit }: {
  ws: string
  tab: WorkspaceTab
  commit?: string
  onTab: (tab: WorkspaceTab) => void
  onCommit: (commit?: string) => void
}) {
  const { t, i18n } = useTranslation()
  useDocumentTitle(ws + " · BDS")
  const workspaces = useQuery(workspacesQuery)
  const workspace = workspaces.data?.find((w) => w.name === ws)
  const commits = useQuery({ ...sysmlCommitsQuery(workspace?.sysml_project ?? ""), enabled: !!workspace })
  const headCommit = commits.data?.[0]?.id
  const cadChangedAt = useBdsFrames(workspace)
  const [editing, setEditing] = useState(false)

  if (workspaces.isPending) return <Skeleton className="m-6 h-40" />
  if (workspaces.isError) return <p className="p-6 text-sm text-destructive">{describeError(workspaces.error)}</p>
  if (!workspace) {
    return (
      <div className="p-10 text-center text-sm text-muted-foreground">
        {t("bds.workspace.notFound", { name: ws })}{" "}
        <Link to="/projects/bds" className="underline">
          {t("bds.workspace.toList")}
        </Link>
      </div>
    )
  }

  const pending = workspace.counts.proposals_pending
  const props: TabProps = { workspace, commit, headCommit, cadChangedAt, onTab }

  return (
    <Tabs value={tab} onValueChange={(value) => onTab(value as WorkspaceTab)} className="gap-0">
      <div className="border-b">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 pt-4">
          <nav aria-label={t("bds.workspace.breadcrumb")} className="text-sm text-muted-foreground">
            <Link to="/projects/bds" className="hover:underline">
              BDS
            </Link>{" "}
            / <span className="text-foreground">{workspace.name}</span>
          </nav>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold">{workspace.name}</h1>
            <span className="text-sm text-muted-foreground">
              {workspace.sysml_project} ↔ {workspace.cad_document || t("bds.workspace.noDocument")}
            </span>
            <span className="ml-auto flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">{t("bds.workspace.version")}</span>
              <Select value={commit ?? "head"} onValueChange={(value) => onCommit(value === "head" ? undefined : value)}>
                <SelectTrigger size="sm" className="w-64">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="head">{t("bds.workspace.head")}</SelectItem>
                  {(commits.data ?? []).map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.id.slice(0, 8)}
                      {c.created ? " · " + new Date(c.created).toLocaleString(i18n.language) : ""}
                      {c.description ? " · " + c.description : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Settings /> {t("bds.workspace.settings")}
              </Button>
            </span>
          </div>
          <TabsList variant="line" className="flex-wrap justify-start pb-1">
            {WORKSPACE_TABS.map((name) => (
              <TabsTrigger
                key={name}
                value={name}
                className="flex-none px-3"
              >
                {t(`bds.tabs.${name}`)}
                {name === "proposals" && pending > 0 && (
                  <span className="ml-1 rounded-full bg-warning/15 px-1.5 text-xs text-warning">{pending}</span>
                )}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </div>

      <div className="mx-auto w-full max-w-6xl p-6">
        <TabsContent value="overview">
          <OverviewTab {...props} />
        </TabsContent>
        <TabsContent value="catalog">
          <CatalogTab {...props} />
        </TabsContent>
        <TabsContent value="proposals">
          <ProposalsTab {...props} />
        </TabsContent>
        <TabsContent value="mapping">
          <MappingTab {...props} />
        </TabsContent>
        <TabsContent value="verify">
          <VerifyTab {...props} />
        </TabsContent>
        <TabsContent value="sync">
          <SyncTab {...props} />
        </TabsContent>
      </div>

      {editing && <WorkspaceDialog open={editing} onOpenChange={setEditing} existing={workspace} />}
    </Tabs>
  )
}
