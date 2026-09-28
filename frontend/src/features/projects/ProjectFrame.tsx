import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import type { ReactNode } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { describeError } from "@/features/cad/format"
import { PROJECT_ROUTES, activateProject, projectsQuery } from "./queries"

/**
 * Rahmen jeder Projektseite. Wechselt ein anderer Tab das aktive Projekt,
 * bekommt DIESES Modul keine FreeCAD-Ereignisse mehr -- das wird hier sichtbar
 * gemacht, statt die Seite stillschweigend veralten zu lassen.
 */
export function ProjectFrame({ id, children }: { id: string; children: ReactNode }) {
  const queryClient = useQueryClient()
  const { data } = useQuery(projectsQuery)
  const active = data?.projects.find((project) => project.active)
  const self = data?.projects.find((project) => project.id === id)
  const switchedAway = data !== undefined && data.active !== id
  const activeRoute = active ? PROJECT_ROUTES[active.id] : undefined

  return (
    <div className="h-full overflow-y-auto">
      {switchedAway && (
        <div className="flex flex-wrap items-center gap-3 border-b border-warning/40 bg-warning/10 px-6 py-2 text-sm">
          <span>
            Das aktive Projekt ist jetzt <strong>{active?.title ?? "keins"}</strong> – diese Seite bekommt keine
            Änderungen aus FreeCAD mehr.
          </span>
          <span className="ml-auto flex gap-2">
            {activeRoute && (
              <Button asChild variant="outline" size="sm">
                <Link to={activeRoute}>Zu {active?.id.toUpperCase()}</Link>
              </Button>
            )}
            <Button
              size="sm"
              onClick={() =>
                activateProject(queryClient, id).catch((error: unknown) => toast.error(describeError(error)))
              }
            >
              {self?.id.toUpperCase() ?? id} wieder aktivieren
            </Button>
          </span>
        </div>
      )}
      {children}
    </div>
  )
}
