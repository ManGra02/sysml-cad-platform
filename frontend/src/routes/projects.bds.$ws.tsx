import { Outlet, createFileRoute, useLocation } from "@tanstack/react-router"
import { z } from "zod"

import { WorkspacePage } from "@/features/bds/WorkspacePage"

// One workspace: the layout around its areas (index = overview, assign, check, limits,
// models). The model state lives in the URL and stays when the area changes -- a link to
// "the check of gearbox at commit X" works.
const searchSchema = z.object({
  commit: z.string().optional().catch(undefined),
})

export const Route = createFileRoute("/projects/bds/$ws")({
  validateSearch: searchSchema,
  component: WorkspaceRoute,
})

function WorkspaceRoute() {
  const { ws } = Route.useParams()
  const { commit } = Route.useSearch()
  const navigate = Route.useNavigate()
  const { pathname } = useLocation()
  return (
    <WorkspacePage ws={ws} commit={commit} onCommit={(next?: string) => void navigate({ to: pathname, search: (s) => ({ ...s, commit: next }) })}>
      <Outlet />
    </WorkspacePage>
  )
}
