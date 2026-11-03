import { createFileRoute } from "@tanstack/react-router"

import { LimitsView } from "@/features/bds/views/LimitsView"

export const Route = createFileRoute("/projects/bds/$ws/limits")({
  component: LimitsView,
})
