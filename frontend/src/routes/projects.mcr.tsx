import { createFileRoute } from "@tanstack/react-router"

import { McrPage } from "@/features/mcr/McrPage"
import { ProjectFrame } from "@/features/projects/ProjectFrame"
import { ensureKnown } from "@/features/projects/queries"

export const Route = createFileRoute("/projects/mcr")({
  beforeLoad: ({ context }) => ensureKnown(context.queryClient, "mcr"),
  component: () => (
    <ProjectFrame id="mcr">
      <McrPage />
    </ProjectFrame>
  ),
})
