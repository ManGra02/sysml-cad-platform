import { useSyncExternalStore } from "react"

// Hell/Dunkel/System, gemerkt im localStorage. Bewusst ohne Zusatzpaket.

export type Theme = "light" | "dark" | "system"

const STORAGE_KEY = "platform.theme"
const listeners = new Set<() => void>()
const media = window.matchMedia("(prefers-color-scheme: dark)")

function read(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === "light" || stored === "dark" ? stored : "system"
  } catch {
    return "system"
  }
}

let current: Theme = read()

function resolve(theme: Theme): "light" | "dark" {
  if (theme === "system") return media.matches ? "dark" : "light"
  return theme
}

function apply() {
  document.documentElement.classList.toggle("dark", resolve(current) === "dark")
  listeners.forEach((listener) => listener())
}

media.addEventListener("change", apply)
apply()

export function setTheme(theme: Theme) {
  current = theme
  try {
    if (theme === "system") localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // ohne Speicher gilt die Wahl nur fuer diese Sitzung
  }
  apply()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, () => current)
  return { theme, resolvedTheme: resolve(theme), setTheme }
}
