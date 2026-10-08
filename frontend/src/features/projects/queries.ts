import { queryOptions, type QueryClient } from "@tanstack/react-query"
import { redirect } from "@tanstack/react-router"

import i18n from "@/i18n"
import { api, seg } from "@/lib/api"
import type { Frame } from "@/lib/ws"

// The project registry lives in the backend. Which project is active is a
// setting of the BACKEND (not of the tab): only then does the right module
// receive the FreeCAD events, even when no tab is showing the project page.

export type ProjectInfo = {
  id: string
  title: string
  description: string
  icon: string
  active: boolean
}

export type ProjectList = { active: string | null; projects: ProjectInfo[] }

/**
 * Projects with their own UI. The routes exist STATICALLY (TanStack
 * Router's type safety is established at build time); the backend only
 * determines which projects exist and which one is active.
 */
export const PROJECT_ROUTES: Partial<Record<string, "/projects/bds" | "/projects/cra">> = {
  bds: "/projects/bds",
  cra: "/projects/cra",
}

/**
 * Description in the UI language. The projects themselves provide it in
 * English (backend); known projects have a translation.
 */
export function projectDescription(project: ProjectInfo): string {
  return i18n.t(("projects.descriptions." + project.id) as never, { defaultValue: project.description })
}

export const projectKeys = {
  list: () => ["projects"] as const,
  module: (id: string) => ["projects", id] as const,
}

export const projectsQuery = queryOptions({
  queryKey: projectKeys.list(),
  queryFn: () => api<ProjectList>("/api/projects"),
  staleTime: Infinity, // changes arrive as "project.activated"/"project.deactivated" via the WebSocket
})

export async function activateProject(queryClient: QueryClient, id: string) {
  const list = await api<ProjectList>("/api/projects/" + seg(id) + "/activate", { method: "POST" })
  queryClient.setQueryData(projectKeys.list(), list)
  return list
}

/** No project active any more -- the start page then shows the pure selection. */
export async function deactivateProject(queryClient: QueryClient) {
  const list = await api<ProjectList>("/api/projects/deactivate", { method: "POST" })
  queryClient.setQueryData(projectKeys.list(), list)
  return list
}

/**
 * beforeLoad of a project route: checks ONLY that the project exists.
 *
 * It deliberately does NOT activate: beforeLoad also runs during preloading,
 * which the router already triggers when a link is hovered ("intent").
 * Activation only happens through a user action (useOpenProject, ProjectFrame).
 */
export async function ensureKnown(queryClient: QueryClient, id: string) {
  const list = await queryClient.ensureQueryData(projectsQuery)
  if (!list.projects.some((project) => project.id === id)) throw redirect({ to: "/" })
}

/** Frames from the backend that concern projects. */
export function handleProjectFrame(queryClient: QueryClient, frame: Frame) {
  if (frame.type === "hello" || frame.type === "project.activated" || frame.type === "project.deactivated") {
    void queryClient.invalidateQueries({ queryKey: projectKeys.list(), exact: true })
    return
  }
  // A module's events carry its id as a prefix: "bds.cad_seen".
  const prefix = frame.type.split(".")[0]
  const list = queryClient.getQueryData<ProjectList>(projectKeys.list())
  if (list?.projects.some((project) => project.id === prefix)) {
    void queryClient.invalidateQueries({ queryKey: projectKeys.module(prefix) })
  }
}
