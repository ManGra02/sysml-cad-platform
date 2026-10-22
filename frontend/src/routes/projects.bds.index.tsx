import { createFileRoute } from "@tanstack/react-router"

import { BdsPage } from "@/features/bds/BdsPage"

export const Route = createFileRoute("/projects/bds/")({
  component: BdsPage,
})
