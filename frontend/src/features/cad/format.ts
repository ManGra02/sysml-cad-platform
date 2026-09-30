import i18n, { TranslatableError, translateIfExists } from "@/i18n"
import { ApiError } from "@/lib/api"
import { quatToAxisAngle } from "./rotation"
import type { ObjRef, PropertyValue } from "./types"

/** Display numbers without float noise (0.30000000000000004 -> 0.3). */
export function formatNumber(value: number, digits = 6): string {
  if (!Number.isFinite(value)) return String(value)
  const rounded = Number(value.toFixed(digits))
  return Object.is(rounded, -0) ? "0" : String(rounded)
}

/** User input as a number; a comma is accepted as the decimal separator. */
export function parseNumber(text: string): number | null {
  const normalized = text.trim().replace(",", ".")
  if (normalized === "" || !/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(normalized)) return null
  const value = Number(normalized)
  return Number.isFinite(value) ? value : null
}

export function refLabel(ref: ObjRef | null, labels?: Record<string, string>): string {
  if (!ref) return "—"
  const label = labels?.[ref.name]
  const base = label && label !== ref.name ? label + " (" + ref.name + ")" : ref.name
  const subs = ref.subs?.length ? " · " + ref.subs.join(", ") : ""
  return base + subs
}

/** Short form for display and table -- never a raw JSON dump. */
export function formatValue(value: PropertyValue, labels?: Record<string, string>): string {
  if (value === null || value === undefined) return "—"
  const t = i18n.t
  if (typeof value === "boolean") return value ? t("common.yes") : t("common.no")
  if (typeof value === "number") return formatNumber(value)
  if (typeof value === "string") return value
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]"
    return "[" + t("common.entries", { count: value.length }) + "]"
  }
  const around = (q: number[]) => {
    const { axis, angle } = quatToAxisAngle(q)
    return {
      zero: Math.abs(angle) < 1e-9,
      text: t("format.around", {
        angle: formatNumber(angle, 3),
        axis: axis.map((n) => formatNumber(n, 3)).join(", "),
      }),
    }
  }
  switch (value.kind) {
    case "quantity":
      return value.text
    case "vector":
      return "(" + [value.x, value.y, value.z].map((n) => formatNumber(n)).join(", ") + ")"
    case "placement": {
      const pos = t("format.pos", { pos: value.pos.map((n) => formatNumber(n)).join(", ") })
      const rotation = around(value.q)
      return rotation.zero ? pos : pos + " · " + rotation.text
    }
    case "rotation":
      return around(value.q).text
    case "matrix":
      return t("format.matrix")
    case "color":
      return "rgba(" + value.rgba.map((n) => formatNumber(n, 3)).join(", ") + ")"
    case "enum":
      return String(value.value)
    case "link":
      return refLabel(value.ref, labels)
    case "link_sub":
      return refLabel(value.ref, labels)
    case "link_list":
    case "link_sub_list":
      return value.refs.length ? value.refs.map((ref) => refLabel(ref, labels)).join(", ") : "—"
    case "material_ref":
      return value.name || value.uuid
    case "map":
      return t("common.entries", { count: Object.keys(value.entries).length })
    case "set":
      return value.values.join(", ")
    case "unsupported":
      return value.summary
  }
}

/** Structural equality for JSON values (field-level conflict detection). */
export function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (typeof a !== typeof b || a === null || b === null || typeof a !== "object") return false
  if (Array.isArray(a) !== Array.isArray(b)) return false
  if (Array.isArray(a)) {
    const other = b as unknown[]
    return a.length === other.length && a.every((item, index) => sameValue(item, other[index]))
  }
  const left = a as Record<string, unknown>
  const right = b as Record<string, unknown>
  const keys = Object.keys(left)
  if (keys.length !== Object.keys(right).length) return false
  return keys.every((key) => sameValue(left[key], right[key]))
}

// -- Error messages ----------------------------------------------------------
//
// Translation is based on the CODES (and, for invalid_value, the `reason`),
// never on the plain-text message -- that is English and only the fallback
// for codes the UI doesn't know (yet).
//
// describeError() is called at DISPLAY time, not when the error occurs: that
// way a visible message changes along when the user switches the language.

type InvalidDetail = { field?: string | null; reason?: string; [param: string]: unknown }

/** field/reason are not parameters, and i18next's own options (count,
 *  context, lng ...) must not slip in as parameters -- they would redirect
 *  the translation instead of being interpolated. */
const NOT_PARAMS = new Set([
  "field",
  "reason",
  "count",
  "context",
  "lng",
  "lngs",
  "ns",
  "defaultValue",
  "ordinal",
  "replace",
  "returnObjects",
])

function reasonParams(detail: InvalidDetail): Record<string, unknown> {
  return Object.fromEntries(Object.entries(detail).filter(([key]) => !NOT_PARAMS.has(key)))
}

/** Message for an invalid value, built from `reason` and its parameters. */
export function describeInvalid(detail: InvalidDetail | undefined, fallback: string): string {
  const reason = detail?.reason ?? "invalid"
  if (reason === "unit_mismatch") {
    const expected = typeof detail?.expected === "string" ? detail.expected : null
    if (!expected) return i18n.t("errors.invalid.unit_mismatch_dimensionless")
    return i18n.t("errors.invalid.unit_mismatch", {
      expected: translateIfExists("unitTypes." + expected) ?? expected,
    })
  }
  return translateIfExists("errors.invalid." + reason, reasonParams(detail ?? {})) ?? fallback
}

/**
 * The reason for an invalid value -- directly in `detail` (PATCH) or one
 * level deeper (POST .../operations reports {failedOp, op, detail}).
 */
function invalidDetail(detail: unknown): InvalidDetail | undefined {
  if (!detail || typeof detail !== "object") return undefined
  const top = detail as InvalidDetail & { detail?: unknown }
  if (top.reason) return top
  if (top.detail && typeof top.detail === "object") return top.detail as InvalidDetail
  return top
}

/** Error phrased so a human knows what to do -- in the UI language. */
export function describeError(error: unknown): string {
  if (error instanceof TranslatableError) return error.translate()
  if (!(error instanceof ApiError)) {
    return error instanceof Error && error.message ? error.message : i18n.t("errors.generic")
  }

  switch (error.code) {
    case "cad_busy": {
      const reason = typeof error.detail === "string" ? error.detail : ""
      return translateIfExists("errors.busy." + reason) ?? i18n.t("errors.busy.fallback")
    }
    case "invalid_value":
      return describeInvalid(invalidDetail(error.detail), error.message)
    case "invalid_patch": {
      const entries = Array.isArray(error.detail)
        ? (error.detail as Array<InvalidDetail & { code?: string; message?: string }>)
        : []
      if (!entries.length) return error.message
      const list = entries
        .map((entry) => {
          const text =
            entry.code === "invalid_value" || entry.code === undefined
              ? describeInvalid(entry, entry.message ?? "")
              : (translateIfExists("errors." + entry.code) ?? entry.message ?? "")
          return entry.field ? entry.field + ": " + text : text
        })
        .join(" · ")
      return i18n.t("errors.invalidFields", { count: entries.length, list })
    }
  }

  // Backend 503 when the bridge is not connected: detail.reason says more precisely why.
  if (error.code.startsWith("bridge_")) {
    const reason = (error.detail as { reason?: string } | undefined)?.reason
    const specific = reason ? translateIfExists("connection.reason." + reason) : undefined
    if (specific) return specific
  }
  return translateIfExists("errors." + error.code) ?? (error.message || i18n.t("errors.generic"))
}
