import { ApiError } from "@/lib/api"
import { quatToAxisAngle } from "./rotation"
import type { ObjRef, PropertyValue } from "./types"

/** Zahlen ohne Float-Rauschen anzeigen (0.30000000000000004 -> 0.3). */
export function formatNumber(value: number, digits = 6): string {
  if (!Number.isFinite(value)) return String(value)
  const rounded = Number(value.toFixed(digits))
  return Object.is(rounded, -0) ? "0" : String(rounded)
}

/** Nutzereingabe als Zahl; Komma wird als Dezimaltrenner akzeptiert. */
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

/** Kurzform fuer Anzeige und Tabelle -- nie ein roher JSON-Dump. */
export function formatValue(value: PropertyValue, labels?: Record<string, string>): string {
  if (value === null || value === undefined) return "—"
  if (typeof value === "boolean") return value ? "ja" : "nein"
  if (typeof value === "number") return formatNumber(value)
  if (typeof value === "string") return value
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]"
    return "[" + value.length + " Eintraege]"
  }
  switch (value.kind) {
    case "quantity":
      return value.text
    case "vector":
      return "(" + [value.x, value.y, value.z].map((n) => formatNumber(n)).join(", ") + ")"
    case "placement": {
      const { axis, angle } = quatToAxisAngle(value.q)
      const pos = value.pos.map((n) => formatNumber(n)).join(", ")
      if (Math.abs(angle) < 1e-9) return "Pos (" + pos + ")"
      return "Pos (" + pos + ") · " + formatNumber(angle, 3) + "° um (" + axis.map((n) => formatNumber(n, 3)).join(", ") + ")"
    }
    case "rotation": {
      const { axis, angle } = quatToAxisAngle(value.q)
      return formatNumber(angle, 3) + "° um (" + axis.map((n) => formatNumber(n, 3)).join(", ") + ")"
    }
    case "matrix":
      return "Matrix 4×4"
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
      return Object.keys(value.entries).length + " Eintraege"
    case "set":
      return value.values.join(", ")
    case "unsupported":
      return value.summary
  }
}

/** Strukturgleichheit fuer JSON-Werte (Konflikterkennung auf Feldebene). */
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

const MESSAGES: Record<string, string> = {
  backend_unreachable: "Das Backend ist nicht erreichbar.",
  bridge_unconfigured: "FreeCAD-Brücke nicht gestartet.",
  bridge_unreachable: "FreeCAD-Brücke nicht erreichbar.",
  gui_busy: "FreeCAD ist beschäftigt und hat nicht rechtzeitig geantwortet.",
  queue_full: "Zu viele Anfragen an FreeCAD auf einmal.",
  doc_not_open: "Das Dokument ist in FreeCAD nicht (mehr) geöffnet.",
  object_not_found: "Das Objekt gibt es nicht (mehr).",
  undo_disabled: "Undo ist für dieses Dokument abgeschaltet.",
  not_writable: "Diese Property ist nicht schreibbar.",
  expression_bound: "Die Property ist an eine Expression gebunden.",
  no_gui: "FreeCAD läuft ohne Oberfläche.",
}

const BUSY_REASONS: Record<string, string> = {
  edit_mode: "In FreeCAD wird gerade ein Objekt bearbeitet (z. B. eine Skizze).",
  task_dialog: "In FreeCAD ist ein Aufgaben-Dialog offen.",
  modal_open: "In FreeCAD ist ein Dialog offen.",
  popup_open: "In FreeCAD ist ein Menü offen.",
  mouse_down: "In FreeCAD ist gerade eine Maustaste gedrückt.",
  transaction_open: "In FreeCAD läuft gerade ein Befehl.",
}

/** Fehler so, dass ein Mensch weiss, was zu tun ist. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : String(error)
  if (error.code === "cad_busy") {
    const reason = typeof error.detail === "string" ? error.detail : undefined
    return (reason && BUSY_REASONS[reason]) || "FreeCAD nimmt gerade keine Änderungen an. " + error.message
  }
  if (error.code === "invalid_value" || error.code === "invalid_patch") return error.message
  return MESSAGES[error.code] ?? error.message
}
