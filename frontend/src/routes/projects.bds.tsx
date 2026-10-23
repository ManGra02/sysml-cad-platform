import { Outlet, createFileRoute } from "@tanstack/react-router"

import { ProjectFrame } from "@/features/projects/ProjectFrame"
import { ensureKnown } from "@/features/projects/queries"

// Layout of the BDS pages: the project frame around the workspace list
// (projects.bds.index) and one workspace (projects.bds.$ws).
export const Route = createFileRoute("/projects/bds")({
  beforeLoad: ({ context }) => ensureKnown(context.queryClient, "bds"),
  component: () => (
    <ProjectFrame id="bds">
      <Outlet />
    </ProjectFrame>
  ),
})
