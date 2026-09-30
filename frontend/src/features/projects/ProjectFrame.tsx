import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useState, type ReactNode } from "react"
import { Trans, useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { describeError } from "@/features/cad/format"
import { useDocumentTitle } from "@/lib/useDocumentTitle"
import { PROJECT_ROUTES, activateProject, projectsQuery } from "./queries"

/**
 * Frame of every project page.
 *
 * The page does NOT activate its project on its own -- not even when opened
 * directly or via the back button. If it is not active (never selected or
 * switched in another tab), this module receives no FreeCAD events; this is
 * made visible here, with a button to activate it.
 */
export function ProjectFrame({ id, children }: { id: string; children: ReactNode }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data } = useQuery(projectsQuery)
  const [pending, setPending] = useState(false)
  const active = data?.projects.find((project) => project.active)
  const self = data?.projects.find((project) => project.id === id)
  const inactive = data !== undefined && data.active !== id
  const activeRoute = active ? PROJECT_ROUTES[active.id] : undefined
  useDocumentTitle(self?.title ?? id.toUpperCase())

  const activate = async () => {
    setPending(true)
    try {
      await activateProject(queryClient, id)
      toast.success(t("projects.activated", { title: self?.title ?? id }))
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      {inactive && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 border-b border-warning/40 bg-warning/10 px-6 py-2 text-sm"
        >
          <span>
            {active ? (
              <Trans i18nKey="projects.currentlyActive" values={{ title: active.title }} components={{ strong: <strong /> }} />
            ) : (
              <Trans i18nKey="projects.notActive" values={{ title: self?.title ?? id }} components={{ strong: <strong /> }} />
            )}
          </span>
          <span className="ml-auto flex gap-2">
            {activeRoute && (
              <Button asChild variant="outline" size="sm">
                <Link to={activeRoute}>{t("projects.goTo", { id: active?.id.toUpperCase() })}</Link>
              </Button>
            )}
            <Button size="sm" disabled={pending} onClick={() => void activate()}>
              {t("projects.activate", { id: (self?.id ?? id).toUpperCase() })}
            </Button>
          </span>
        </div>
      )}
      {children}
    </div>
  )
}
