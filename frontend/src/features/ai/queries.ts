import { queryOptions } from "@tanstack/react-query"

import { api } from "@/lib/api"

// The AI side of the platform: the backend talks to Ollama Cloud
// (backend/app/ai) and gives every project its own model. The browser only
// sees the status -- the API key never leaves the backend.

export type AiProjectModel = {
  model: string | null
  /** Only set when Ollama was reachable. */
  available?: boolean
}

export type AiStatus = {
  provider: "ollama-cloud"
  url: string
  configured: boolean
  reachable: boolean
  /** Cloud models Ollama offers -- only set when reachable. */
  models?: string[]
  code?: string
  message?: string
  checkedAt: number
  projects: Record<string, AiProjectModel>
}

/** ok: reachable and every project's model exists. */
export type AiState = "ok" | "model_missing" | "unreachable" | "unconfigured"

export function aiState(status: AiStatus): AiState {
  if (!status.configured) return "unconfigured"
  if (!status.reachable) return "unreachable"
  return Object.values(status.projects).every((p) => p.available) ? "ok" : "model_missing"
}

export const aiKeys = {
  all: ["ai"] as const,
  status: () => [...aiKeys.all, "status"] as const,
}

export const aiStatusQuery = queryOptions({
  queryKey: aiKeys.status(),
  queryFn: ({ signal }) => api<AiStatus>("/api/ai/status", { signal }),
  // The backend caches the check for 30 s, so polling more often gains nothing.
  refetchInterval: 30_000,
})

/** Bypasses the backend's cache -- for the "check now" button. */
export const refreshAiStatus = () => api<AiStatus>("/api/ai/status", { query: { refresh: "true" } })
