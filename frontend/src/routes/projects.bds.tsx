import { createFileRoute } from "@tanstack/react-router"

import { BdsPage } from "@/features/bds/BdsPage"
import { ProjectFrame } from "@/features/projects/ProjectFrame"
import { ensureActive } from "@/features/projects/queries"

export const Route = createFileRoute("/projects/bds")({
  beforeLoad: ({ context }) => ensureActive(context.queryClient, "bds"),
  component: () => (
    <ProjectFrame id="bds">
      <BdsPage />
    </ProjectFrame>
  ),
})
