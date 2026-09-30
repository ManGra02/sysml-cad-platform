import { afterEach, describe, expect, it } from "vitest"

import { describeError, formatValue } from "@/features/cad/format"
import { ApiError } from "@/lib/api"
import i18n, { DEFAULT_LANGUAGE, TranslatableError } from "."
import de from "./locales/de.json"
import en from "./locales/en.json"

function keys(tree: object, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === "string" ? [prefix + key] : keys(value as object, prefix + key + "."),
  )
}

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{\{(\w+)\}\}|<(\w+)>/g)].map((match) => match[1] ?? match[2]).sort()
}

afterEach(() => i18n.changeLanguage(DEFAULT_LANGUAGE))

describe("Languages", () => {
  it("English is the default", () => {
    expect(DEFAULT_LANGUAGE).toBe("en")
    expect(i18n.language).toBe("en")
  })

  it("German has exactly the same keys", () => {
    expect(keys(de).sort()).toEqual(keys(en).sort())
  })

  it("placeholders and tags match in both languages", () => {
    const german = new Map(
      keys(de).map((key) => [key, key.split(".").reduce<unknown>((node, part) => (node as never)[part], de) as string]),
    )
    for (const key of keys(en)) {
      const english = key.split(".").reduce<unknown>((node, part) => (node as never)[part], en) as string
      expect(placeholders(german.get(key)!), key).toEqual(placeholders(english))
    }
  })
})

describe("Errors in the UI language", () => {
  const unit = new ApiError(400, "invalid_value", "Length: unit does not match, expected Length", {
    field: "Length",
    reason: "unit_mismatch",
    expected: "Length",
  })

  it("translates based on the reason, not the message", async () => {
    expect(describeError(unit)).toBe("Wrong unit – expected: length.")
    await i18n.changeLanguage("de")
    expect(describeError(unit)).toBe("Falsche Einheit – erwartet: Länge.")
  })

  it("parameters end up in the message", async () => {
    await i18n.changeLanguage("de")
    const error = new ApiError(400, "invalid_value", "…", { field: "Length", reason: "quantity_invalid", input: "abc" })
    expect(describeError(error)).toBe("„abc“ ist keine gültige Menge.")
  })

  it("multiple fields are translated individually", () => {
    const error = new ApiError(400, "invalid_patch", "2 fields are invalid", [
      { code: "invalid_value", field: "Width", reason: "quantity_invalid", input: "x" },
      { code: "not_writable", field: "Shape", message: "Shape is not writable" },
    ])
    expect(describeError(error)).toBe(
      "2 fields are invalid: Width: “x” is not a valid quantity. · Shape: This property is not writable.",
    )
  })

  it("reason for a lock in FreeCAD", async () => {
    await i18n.changeLanguage("de")
    expect(describeError(new ApiError(409, "cad_busy", "CAD is currently not writable", "edit_mode"))).toBe(
      "In FreeCAD wird gerade ein Objekt bearbeitet (z. B. eine Skizze).",
    )
  })

  it("bridge status with exact reason", () => {
    const error = new ApiError(503, "bridge_unconfigured", "FreeCAD bridge not started (orphaned handshake file)", {
      state: "unconfigured",
      reason: "orphaned_handshake",
    })
    expect(describeError(error)).toBe("The handshake file is left over from a FreeCAD that is no longer running.")
  })

  it("unknown code falls back to the (English) message", async () => {
    await i18n.changeLanguage("de")
    expect(describeError(new ApiError(500, "brand_new_code", "Something new happened"))).toBe("Something new happened")
  })
})

describe("Values in the UI language", () => {
  it("yes/no and rotations", async () => {
    expect(formatValue(true)).toBe("yes")
    const placement = { kind: "placement" as const, pos: [1, 0, 0], q: [0, 0, Math.SQRT1_2, Math.SQRT1_2] }
    expect(formatValue(placement)).toBe("Pos (1, 0, 0) · 90° around (0, 0, 1)")
    await i18n.changeLanguage("de")
    expect(formatValue(true)).toBe("ja")
    expect(formatValue(placement)).toBe("Pos (1, 0, 0) · 90° um (0, 0, 1)")
  })
})

describe("Errors that switch with the language", () => {
  it("TranslatableError is translated when displayed, not when created", async () => {
    const error = new TranslatableError("fields.numberExpected")
    expect(describeError(error)).toBe("Number expected")
    await i18n.changeLanguage("de")
    expect(describeError(error)).toBe("Zahl erwartet")
  })

  it("ApiError is re-translated on every display", async () => {
    const error = new ApiError(404, "object_not_found", "Object 'Box' does not exist")
    expect(describeError(error)).toBe("The object does not exist (anymore).")
    await i18n.changeLanguage("de")
    expect(describeError(error)).toBe("Das Objekt gibt es nicht (mehr).")
  })
})

describe("Errors from POST .../operations", () => {
  it("the reason may be nested one level deeper", async () => {
    await i18n.changeLanguage("de")
    const error = new ApiError(400, "invalid_value", "Length: integer expected", {
      failedOp: 1,
      op: "patch",
      detail: { field: "Length", reason: "int_expected" },
    })
    expect(describeError(error)).toBe("Ganzzahl erwartet.")
  })

  it("i18next's own options in the detail do not redirect the translation", () => {
    const error = new ApiError(400, "invalid_value", "…", {
      field: "Mode",
      reason: "enum_choice",
      value: "Foo",
      lng: "de",
      count: 3,
    })
    expect(describeError(error)).toBe("“Foo” is not an allowed choice.")
  })
})
