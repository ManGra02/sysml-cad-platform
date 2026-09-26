// Der einzige Weg des Browsers nach draussen: das Backend, same-origin.
// Der Browser kennt die Bruecke nicht und sieht nie ihr Token.

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: unknown
  readonly requestId?: string

  constructor(status: number, code: string, message: string, detail?: unknown, requestId?: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.detail = detail
    this.requestId = requestId
  }
}

type ErrorBody = {
  error?: { code?: string; message?: string; detail?: unknown; request_id?: string }
}

export type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"
  body?: unknown
  query?: Record<string, string | undefined>
  requestId?: string
  ifMatch?: number
  signal?: AbortSignal
}

/** Pro Mutation eine eigene ID: sie macht Wiederholungen idempotent und das Echo erkennbar. */
export function newRequestId(): string {
  return crypto.randomUUID()
}

/** Pfadsegmente IMMER kodieren: Objektnamen duerfen beliebiges Unicode enthalten. */
export function seg(value: string): string {
  return encodeURIComponent(value)
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" }
  if (options.body !== undefined) headers["Content-Type"] = "application/json"
  if (options.requestId) headers["X-Request-Id"] = options.requestId
  if (options.ifMatch !== undefined) headers["If-Match"] = '"' + options.ifMatch + '"'

  let url = path
  if (options.query) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(options.query)) {
      if (value !== undefined) params.set(key, value)
    }
    const text = params.toString()
    if (text) url += "?" + text
  }

  let response: Response
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error
    throw new ApiError(0, "backend_unreachable", "Backend nicht erreichbar", undefined, options.requestId)
  }

  const text = await response.text()
  let payload: unknown = undefined
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = undefined
    }
  }

  if (!response.ok) {
    const error = (payload as ErrorBody | undefined)?.error
    throw new ApiError(
      response.status,
      error?.code ?? "http_" + response.status,
      error?.message ?? response.statusText,
      error?.detail,
      error?.request_id ?? options.requestId,
    )
  }
  return payload as T
}

/** Fehler, bei denen eine Wiederholung nichts aendert (4xx) -- nicht automatisch neu versuchen. */
export function isFinal(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 400 && error.status < 500
}
