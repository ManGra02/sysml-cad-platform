import { useQuery, type QueryClient } from "@tanstack/react-query"
import { Link, Outlet, createRootRouteWithContext } from "@tanstack/react-router"
import { Monitor, Moon, Sun } from "lucide-react"

import logo from "@/assets/logo.svg"
import { Button } from "@/components/ui/button"
import { ConnectionStatus } from "@/features/cad/components/ConnectionStatus"
import { describeError } from "@/features/cad/format"
import { ProjectIcon } from "@/features/projects/ProjectIcon"
import { PROJECT_ROUTES, projectsQuery } from "@/features/projects/queries"
import { useTheme, type Theme } from "@/lib/theme"

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
  errorComponent: ({ error }) => (
    <div className="p-10 text-center text-sm">
      <p className="mb-2 font-medium">Das hat nicht geklappt.</p>
      <p className="text-muted-foreground">{describeError(error)}</p>
      <Link to="/" className="mt-4 inline-block underline">
        Zur Projektauswahl
      </Link>
    </div>
  ),
  notFoundComponent: () => (
    <div className="p-10 text-center text-sm text-muted-foreground">
      Diese Seite gibt es nicht.{" "}
      <Link to="/cad" className="underline">
        Zum CAD-Explorer
      </Link>
    </div>
  ),
})

function RootLayout() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b px-4">
        <Link to="/" className="flex items-center gap-2 font-semibold">
          <img src={logo} alt="" className="size-5" />
          SysML-CAD Platform
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <ActiveProjectLink />
          <Link
            to="/cad"
            className={NAV_LINK}
            activeProps={{ className: "bg-accent text-foreground" }}
          >
            CAD-Explorer
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <ConnectionStatus />
          <ThemeToggle />
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}

const NAV_LINK = "flex items-center gap-1.5 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground"

/** Das aktive Projekt -- oder der Weg zur Auswahl, wenn noch keins gewaehlt ist. */
function ActiveProjectLink() {
  const { data } = useQuery(projectsQuery)
  const active = data?.projects.find((project) => project.active)
  const to = active ? PROJECT_ROUTES[active.id] : undefined
  if (!active || !to) {
    return (
      <Link to="/" className={NAV_LINK} activeProps={{ className: "bg-accent text-foreground" }} activeOptions={{ exact: true }}>
        Projekt wählen
      </Link>
    )
  }
  return (
    <Link to={to} className={NAV_LINK} activeProps={{ className: "bg-accent text-foreground" }} title={active.title}>
      <ProjectIcon name={active.icon} className="size-3.5" />
      {active.id.toUpperCase()}
    </Link>
  )
}

const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" }
const ICON = { system: Monitor, light: Sun, dark: Moon }
const LABEL = { system: "Design: System", light: "Design: Hell", dark: "Design: Dunkel" }

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const Icon = ICON[theme]
  return (
    <Button variant="ghost" size="icon-sm" title={LABEL[theme]} onClick={() => setTheme(NEXT[theme])}>
      <Icon />
    </Button>
  )
}
