import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Trans, useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { describeError } from "@/features/cad/format"
import { TitleScope, useDocumentTitle } from "@/lib/useDocumentTitle"
import { PROJECT_ROUTES, activateProject, projectsQuery } from "./queries"

/**
 * Frame of every project page.
 *
 * When NO project is active, opening a project page activates it -- there is nothing to
 * take over from. When ANOTHER project is active (switched in another tab), the page never
 * takes over on its own: it says calmly that FreeCAD changes reach it only on demand, and
 * offers to switch.
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
  useDocumentTitle(self?.title ?? id)

  const autoActivated = useRef(false)
  useEffect(() => {
    if (!data || data.active || !self || autoActivated.current) return
    autoActivated.current = true
    activateProject(queryClient, id).catch(() => {
      autoActivated.current = false
    })
  }, [data, self, id, queryClient])

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
      {inactive && active && (
        <div role="status" className="flex flex-wrap items-center gap-3 border-b bg-muted/40 px-6 py-2 text-sm text-muted-foreground">
          <span className="flex-1">
            <Trans i18nKey="projects.otherActive" values={{ title: active.title }} components={{ strong: <strong className="text-foreground" /> }} />
          </span>
          <span className="flex gap-2">
            {activeRoute && (
              <Button asChild variant="ghost" size="sm">
                <Link to={activeRoute}>{t("projects.goTo", { title: active.title })}</Link>
              </Button>
            )}
            <Button variant="outline" size="sm" disabled={pending} onClick={() => void activate()}>
              {t("projects.switchHere")}
            </Button>
          </span>
        </div>
      )}
      <TitleScope>{children}</TitleScope>
    </div>
  )
}
