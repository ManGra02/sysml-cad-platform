import { createFileRoute } from "@tanstack/react-router"

import { ModelsView } from "@/features/bds/views/ModelsView"

export const Route = createFileRoute("/projects/bds/$ws/models")({
  component: ModelsView,
})
