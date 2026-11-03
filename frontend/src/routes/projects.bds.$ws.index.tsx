import { createFileRoute } from "@tanstack/react-router"

import { OverviewView } from "@/features/bds/views/OverviewView"

export const Route = createFileRoute("/projects/bds/$ws/")({
  component: OverviewView,
})
