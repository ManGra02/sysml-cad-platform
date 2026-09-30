import { useQuery, type QueryClient } from "@tanstack/react-query"
import { Link, Outlet, createRootRouteWithContext } from "@tanstack/react-router"
import { Languages, Monitor, Moon, Sun } from "lucide-react"
import { useTranslation } from "react-i18next"

import logo from "@/assets/logo.svg"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ConnectionStatus } from "@/features/cad/components/ConnectionStatus"
import { describeError } from "@/features/cad/format"
import { ProjectIcon } from "@/features/projects/ProjectIcon"
import { PROJECT_ROUTES, projectsQuery } from "@/features/projects/queries"
import { LANGUAGES, useLanguage, type Language } from "@/i18n"
import { useTheme, type Theme } from "@/lib/theme"

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
  errorComponent: ({ error }) => <RootError error={error} />,
  notFoundComponent: NotFound,
})

function RootError({ error }: { error: unknown }) {
  const { t } = useTranslation()
  return (
    <div className="p-10 text-center text-sm">
      <p className="mb-2 font-medium">{t("root.errorTitle")}</p>
      <p className="text-muted-foreground">{describeError(error)}</p>
      <Link to="/" className="mt-4 inline-block underline">
        {t("root.toProjects")}
      </Link>
    </div>
  )
}

function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="p-10 text-center text-sm text-muted-foreground">
      {t("root.notFound")}{" "}
      <Link to="/cad" className="underline">
        {t("root.toExplorer")}
      </Link>
    </div>
  )
}

function RootLayout() {
  const { t } = useTranslation()
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b px-4">
        <Link to="/" className="flex items-center gap-2 font-semibold">
          <img src={logo} alt="" className="size-5" />
          {t("app.name")}
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <ActiveProjectLink />
          <Link
            to="/cad"
            className={NAV_LINK}
            activeProps={{ className: "bg-accent text-foreground" }}
          >
            {t("nav.cadExplorer")}
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <ConnectionStatus />
          <LanguageSwitcher />
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

/** The active project -- or the way to the selection if none is chosen yet. */
function ActiveProjectLink() {
  const { t } = useTranslation()
  const { data } = useQuery(projectsQuery)
  const active = data?.projects.find((project) => project.active)
  const to = active ? PROJECT_ROUTES[active.id] : undefined
  if (!active || !to) {
    return (
      <Link to="/" className={NAV_LINK} activeProps={{ className: "bg-accent text-foreground" }} activeOptions={{ exact: true }}>
        {t("nav.chooseProject")}
      </Link>
    )
  }
  return (
    <Link
      to={to}
      className={NAV_LINK}
      activeProps={{ className: "bg-accent text-foreground" }}
      title={t("nav.activeProject", { title: active.title })}
    >
      <ProjectIcon name={active.icon} className="size-3.5" />
      {active.id.toUpperCase()}
    </Link>
  )
}

const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" }
const ICON = { system: Monitor, light: Sun, dark: Moon }
function LanguageSwitcher() {
  const { t } = useTranslation()
  const { language, setLanguage } = useLanguage()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5 px-2" title={t("language.label")} aria-label={t("language.label")}>
          <Languages />
          <span className="text-xs font-medium uppercase">{language}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{t("language.label")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup value={language} onValueChange={(value) => setLanguage(value as Language)}>
          {LANGUAGES.map((code) => (
            // Each language in its own language -- so anyone who can't read the current one finds theirs.
            <DropdownMenuRadioItem key={code} value={code} lang={code}>
              {t(`language.${code}`)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ThemeToggle() {
  const { t } = useTranslation()
  const { theme, setTheme } = useTheme()
  const Icon = ICON[theme]
  return (
    <Button variant="ghost" size="icon-sm" title={t(`theme.${theme}`)} onClick={() => setTheme(NEXT[theme])}>
      <Icon />
    </Button>
  )
}
