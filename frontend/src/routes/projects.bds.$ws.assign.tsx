import { createFileRoute } from "@tanstack/react-router"

import { AssignView } from "@/features/bds/views/AssignView"

export const Route = createFileRoute("/projects/bds/$ws/assign")({
  component: AssignView,
})
