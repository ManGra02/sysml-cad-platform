import { createFileRoute, redirect } from "@tanstack/react-router"

// Hier entsteht in M7 der Launcher (Projekt-Auswahl). Bis dahin: CAD-Explorer.
export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/cad" })
  },
})
