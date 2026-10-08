import { createFileRoute } from "@tanstack/react-router"

import { CraPage } from "@/features/cra/CraPage"
import { ProjectFrame } from "@/features/projects/ProjectFrame"
import { ensureKnown } from "@/features/projects/queries"

export const Route = createFileRoute("/projects/cra")({
  beforeLoad: ({ context }) => ensureKnown(context.queryClient, "cra"),
  component: () => (
    <ProjectFrame id="cra">
      <CraPage />
    </ProjectFrame>
  ),
})
