import { createFileRoute } from "@tanstack/react-router"

import { CheckView } from "@/features/bds/views/CheckView"

export const Route = createFileRoute("/projects/bds/$ws/check")({
  component: CheckView,
})
