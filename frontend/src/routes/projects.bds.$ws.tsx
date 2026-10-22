import { createFileRoute } from "@tanstack/react-router"
import { z } from "zod"

import { WORKSPACE_TABS, WorkspacePage, type WorkspaceTab } from "@/features/bds/WorkspacePage"

// The tab and the model state live in the URL: a link to "the proposals of gearbox at
// commit X" works, and the back button goes back through the tabs.
const searchSchema = z.object({
  tab: z.enum(WORKSPACE_TABS).optional().catch(undefined),
  commit: z.string().optional().catch(undefined),
})

export const Route = createFileRoute("/projects/bds/$ws")({
  validateSearch: searchSchema,
  component: WorkspaceRoute,
})

function WorkspaceRoute() {
  const { ws } = Route.useParams()
  const { tab, commit } = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <WorkspacePage
      ws={ws}
      tab={tab ?? "overview"}
      commit={commit}
      onTab={(next: WorkspaceTab) => void navigate({ search: (s) => ({ ...s, tab: next === "overview" ? undefined : next }) })}
      onCommit={(next?: string) => void navigate({ search: (s) => ({ ...s, commit: next }) })}
    />
  )
}
