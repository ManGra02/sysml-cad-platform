import { createFileRoute } from "@tanstack/react-router"

import { SysmlPage } from "@/features/sysml/SysmlPage"

export const Route = createFileRoute("/sysml")({
  component: SysmlPage,
})
