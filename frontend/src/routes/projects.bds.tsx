import { createFileRoute } from "@tanstack/react-router"

import { BdsPage } from "@/features/bds/BdsPage"
import { ProjectFrame } from "@/features/projects/ProjectFrame"
import { ensureKnown } from "@/features/projects/queries"

export const Route = createFileRoute("/projects/bds")({
  beforeLoad: ({ context }) => ensureKnown(context.queryClient, "bds"),
  component: () => (
    <ProjectFrame id="bds">
      <BdsPage />
    </ProjectFrame>
  ),
})
