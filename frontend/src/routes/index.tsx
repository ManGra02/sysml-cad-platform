import { useQuery } from "@tanstack/react-query"
import { Link, createFileRoute } from "@tanstack/react-router"
import { ArrowRight, Box } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { ProjectIcon } from "@/features/projects/ProjectIcon"
import { PROJECT_ROUTES, projectsQuery } from "@/features/projects/queries"
import { cn } from "@/lib/utils"

// Der Launcher: welches Projekt? Reine Modus-Umschaltung, keine Projektdatei.
// Die Karte fuehrt auf /projects/<id>; deren beforeLoad schaltet im Backend um.
export const Route = createFileRoute("/")({
  component: Launcher,
})

function Launcher() {
  const query = useQuery(projectsQuery)

  return (
    <div className="mx-auto max-w-4xl p-6 sm:p-10">
      <h1 className="mb-1 text-2xl font-semibold">Woran arbeitest du?</h1>
      <p className="mb-8 text-sm text-muted-foreground">
        Die Wahl gilt für alle offenen Tabs und bestimmt, welches Projekt die Änderungen aus FreeCAD bekommt. Der
        CAD-Explorer steht in jedem Projekt zur Verfügung.
      </p>

      {query.isPending && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      )}
      {query.isError && <p className="text-sm text-destructive">{describeError(query.error)}</p>}

      <div className="grid gap-4 sm:grid-cols-2">
        {query.data?.projects.map((project) => {
          const to = PROJECT_ROUTES[project.id]
          const card = (
            <Card
              className={cn(
                "h-full transition-colors",
                to ? "hover:bg-muted/50" : "opacity-60",
                project.active && "border-primary",
              )}
            >
              <CardHeader>
                <div className="mb-2 flex items-center justify-between">
                  <div className="grid size-10 place-items-center rounded-lg bg-muted">
                    <ProjectIcon name={project.icon} className="size-5" />
                  </div>
                  {project.active && <Badge>aktiv</Badge>}
                </div>
                <CardTitle className="flex items-center gap-2">
                  {project.title}
                  {to && <ArrowRight className="size-4 text-muted-foreground" />}
                </CardTitle>
                <CardDescription>{project.description}</CardDescription>
                {!to && (
                  <p className="text-xs text-muted-foreground">
                    Oberfläche fehlt noch: <code>frontend/src/routes/projects.{project.id}.tsx</code>
                  </p>
                )}
              </CardHeader>
            </Card>
          )
          return to ? (
            <Link key={project.id} to={to} className="block">
              {card}
            </Link>
          ) : (
            <div key={project.id}>{card}</div>
          )
        })}
      </div>

      <Link
        to="/cad"
        className="mt-8 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <Box className="size-4" /> Nur den CAD-Explorer öffnen
      </Link>
    </div>
  )
}
