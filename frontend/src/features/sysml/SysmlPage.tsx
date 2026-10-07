import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { useTranslation } from "react-i18next"

import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { useDocumentTitle } from "@/lib/useDocumentTitle"

import { ModelView } from "./components/ModelView"
import { ProjectBar } from "./components/ProjectBar"
import { StatusCard } from "./components/StatusCard"
import { sysmlProjectsQuery, sysmlSnapshotQuery, sysmlStatusQuery } from "./queries"

/**
 * Read-only view of the SysML v2 model in Flexo -- the same data as /api/sysml/*, for humans.
 * This page only decides WHAT to load (status -> projects -> snapshot of the chosen project);
 * how each part looks lives in ./components.
 */
export function SysmlPage() {
  const { t } = useTranslation()
  useDocumentTitle(t("sysml.pageTitle"))
  const status = useQuery(sysmlStatusQuery)
  const reachable = status.data?.reachable === true
  const projects = useQuery({ ...sysmlProjectsQuery, enabled: reachable })
  const [chosen, setChosen] = useState<string | null>(null)
  const project = chosen ?? projects.data?.[0]?.id ?? null
  const snapshot = useQuery({ ...sysmlSnapshotQuery(project ?? ""), enabled: reachable && project !== null })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="mb-1 text-xl font-semibold">{t("sysml.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("sysml.hint")}</p>
      </div>

      <StatusCard />

      {reachable && projects.isPending && <Skeleton className="h-10 w-72" />}
      {projects.isError && <p className="text-sm text-destructive">{describeError(projects.error)}</p>}
      {projects.data && projects.data.length === 0 && (
        <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
          <p className="mb-2">{t("sysml.noProjects")}</p>
          <code className="rounded bg-muted px-2 py-1 text-xs">uv run python -m app.sysml seed-demo</code>
        </div>
      )}

      {projects.data && projects.data.length > 0 && project && (
        <ProjectBar
          projects={projects.data}
          project={project}
          onProjectChange={setChosen}
          version={snapshot.data?.version}
          reloading={snapshot.isFetching}
          onReload={() => void snapshot.refetch()}
        />
      )}

      {snapshot.isPending && project && reachable && (
        <div className="grid gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      )}
      {snapshot.isError && <p className="text-sm text-destructive">{describeError(snapshot.error)}</p>}
      {snapshot.data && project && <ModelView snapshot={snapshot.data} project={project} />}
    </div>
  )
}
