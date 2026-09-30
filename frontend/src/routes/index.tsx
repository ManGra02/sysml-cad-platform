import { useQuery } from "@tanstack/react-query"
import { Link, createFileRoute } from "@tanstack/react-router"
import { ArrowRight, Box, Loader2 } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { ProjectIcon } from "@/features/projects/ProjectIcon"
import { PROJECT_ROUTES, projectDescription, projectsQuery, type ProjectInfo } from "@/features/projects/queries"
import { useOpenProject } from "@/features/projects/useOpenProject"
import { useDocumentTitle } from "@/lib/useDocumentTitle"
import { cn } from "@/lib/utils"

// The launcher. Pure mode switching, no project file.
// Hovering only highlights; ACTIVATION happens only on click (useOpenProject).
export const Route = createFileRoute("/")({
  component: Launcher,
})

function Launcher() {
  const { t } = useTranslation()
  useDocumentTitle()
  const query = useQuery(projectsQuery)
  const { open, pending } = useOpenProject()
  const projects = query.data?.projects ?? []
  const active = projects.find((project) => project.active)
  const others = projects.filter((project) => !project.active)

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl p-6 sm:p-10">
        {query.isPending && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Skeleton className="h-36" />
            <Skeleton className="h-36" />
          </div>
        )}
        {query.isError && <p className="text-sm text-destructive">{describeError(query.error)}</p>}

        {active && (
          <section className="mb-10">
            <h1 className="mb-1 text-2xl font-semibold">{t("launcher.activeTitle")}</h1>
            <p className="mb-4 text-sm text-muted-foreground">
              {t("launcher.activeHint")}
            </p>
            <div className="flex flex-col gap-4 rounded-xl border border-primary/40 bg-card p-5 sm:flex-row sm:items-center">
              <div className="grid size-12 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground">
                <ProjectIcon name={active.icon} className="size-6" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 font-semibold">
                  {active.title} <Badge>{t("common.active")}</Badge>
                </p>
                <p className="text-sm text-muted-foreground">{projectDescription(active)}</p>
              </div>
              {PROJECT_ROUTES[active.id] && (
                <Button size="lg" onClick={() => void open(active.id)} disabled={pending !== null}>
                  {pending === active.id ? <Loader2 className="animate-spin" /> : null}
                  {t("launcher.continue")} <ArrowRight />
                </Button>
              )}
            </div>
          </section>
        )}

        {query.data && (
          <section>
            <h2 className={cn("mb-1 font-semibold", active ? "text-lg" : "text-2xl")}>
              {active ? t("launcher.switchTitle") : t("launcher.chooseTitle")}
            </h2>
            <p className="mb-4 text-sm text-muted-foreground">
              {active ? t("launcher.switchHint", { title: active.title }) : t("launcher.chooseHint")}
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              {others.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  pending={pending === project.id}
                  disabled={pending !== null}
                  onOpen={() => void open(project.id)}
                />
              ))}
            </div>
          </section>
        )}

        <Link
          to="/cad"
          className="mt-8 inline-flex items-center gap-2 rounded-md text-sm text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <Box className="size-4" /> {t("launcher.openExplorerOnly")}
        </Link>
      </div>
    </div>
  )
}

function ProjectCard({
  project,
  pending,
  disabled,
  onOpen,
}: {
  project: ProjectInfo
  pending: boolean
  disabled: boolean
  onOpen: () => void
}) {
  const { t } = useTranslation()
  const available = Boolean(PROJECT_ROUTES[project.id])
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!available || disabled}
      aria-label={t("launcher.activateAndOpenLabel", { title: project.title })}
      className={cn(
        "group flex h-full flex-col gap-3 rounded-xl border bg-card p-5 text-left shadow-xs transition-colors",
        "outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
        available ? "hover:border-foreground/30 hover:bg-muted/50" : "cursor-not-allowed opacity-60",
        pending && "border-primary/60",
      )}
    >
      <div className="grid size-10 place-items-center rounded-lg bg-muted transition-colors group-hover:bg-background">
        <ProjectIcon name={project.icon} className="size-5" />
      </div>
      <div>
        <p className="flex items-center gap-2 font-semibold">{project.title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{projectDescription(project)}</p>
      </div>
      <p className="mt-auto flex items-center gap-1 text-sm font-medium text-muted-foreground group-hover:text-foreground">
        {available ? (
          <>
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            {t("launcher.activateAndOpen")}
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
          </>
        ) : (
          <span className="text-xs font-normal">
            {t("launcher.uiMissing")} <code>frontend/src/routes/projects.{project.id}.tsx</code>
          </span>
        )}
      </p>
    </button>
  )
}
