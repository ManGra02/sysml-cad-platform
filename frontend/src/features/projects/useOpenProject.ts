import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import { toast } from "sonner"

import { describeError } from "@/features/cad/format"
import i18n from "@/i18n"
import { PROJECT_ROUTES, activateProject, projectKeys, type ProjectList } from "./queries"

/**
 * Open a project -- and activate it along the way if it isn't already.
 * The ONLY way the start page activates a project: by a click.
 */
export function useOpenProject() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [pending, setPending] = useState<string | null>(null)

  const open = async (id: string) => {
    const to = PROJECT_ROUTES[id]
    if (!to || pending) return
    const list = queryClient.getQueryData<ProjectList>(projectKeys.list())
    setPending(id)
    try {
      if (list?.active !== id) {
        const updated = await activateProject(queryClient, id)
        const title = updated.projects.find((project) => project.id === id)?.title ?? id
        toast.success(i18n.t("projects.activated", { title }))
      }
      await navigate({ to })
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(null)
    }
  }

  return { open, pending }
}
