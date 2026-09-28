import { queryOptions, type QueryClient } from "@tanstack/react-query"
import { redirect } from "@tanstack/react-router"

import { api, seg } from "@/lib/api"
import type { Frame } from "@/lib/ws"

// Die Projekt-Registry lebt im Backend. Welches Projekt aktiv ist, ist eine
// Einstellung des BACKENDS (nicht des Tabs): nur so bekommt das richtige Modul
// die FreeCAD-Ereignisse, auch wenn gerade kein Tab die Projektseite zeigt.

export type ProjectInfo = {
  id: string
  title: string
  description: string
  icon: string
  active: boolean
}

export type ProjectList = { active: string | null; projects: ProjectInfo[] }

/**
 * Projekte mit eigener Oberflaeche. Die Routen existieren STATISCH (TanStack
 * Routers Typsicherheit entsteht zur Build-Zeit); das Backend bestimmt nur,
 * welche Projekte es gibt und welches aktiv ist.
 */
export const PROJECT_ROUTES: Partial<Record<string, "/projects/bds" | "/projects/mcr">> = {
  bds: "/projects/bds",
  mcr: "/projects/mcr",
}

export const projectKeys = {
  list: () => ["projects"] as const,
  module: (id: string) => ["projects", id] as const,
}

export const projectsQuery = queryOptions({
  queryKey: projectKeys.list(),
  queryFn: () => api<ProjectList>("/api/projects"),
  staleTime: Infinity, // Wechsel kommen als "project.activated" ueber den WebSocket
})

export async function activateProject(queryClient: QueryClient, id: string) {
  const list = await api<ProjectList>("/api/projects/" + seg(id) + "/activate", { method: "POST" })
  queryClient.setQueryData(projectKeys.list(), list)
  return list
}

/**
 * beforeLoad einer Projektroute: die URL IST der Modus. Wer /projects/bds
 * oeffnet (auch per Lesezeichen), schaltet damit auf BDS um.
 */
export async function ensureActive(queryClient: QueryClient, id: string) {
  const list = await queryClient.ensureQueryData(projectsQuery)
  if (!list.projects.some((project) => project.id === id)) throw redirect({ to: "/" })
  if (list.active !== id) await activateProject(queryClient, id)
}

/** Frames vom Backend, die Projekte betreffen. */
export function handleProjectFrame(queryClient: QueryClient, frame: Frame) {
  if (frame.type === "hello" || frame.type === "project.activated") {
    void queryClient.invalidateQueries({ queryKey: projectKeys.list(), exact: true })
    return
  }
  // Ereignisse eines Moduls tragen seine id als Praefix: "bds.cad_seen".
  const prefix = frame.type.split(".")[0]
  const list = queryClient.getQueryData<ProjectList>(projectKeys.list())
  if (list?.projects.some((project) => project.id === prefix)) {
    void queryClient.invalidateQueries({ queryKey: projectKeys.module(prefix) })
  }
}
