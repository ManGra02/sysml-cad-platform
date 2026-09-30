import i18n, { type TOptions } from "i18next"
import { initReactI18next, useTranslation } from "react-i18next"

import de from "./locales/de.json"
import en from "./locales/en.json"

// English is the default -- regardless of the browser language. The user's
// choice is remembered in localStorage (per browser, not per tab).
//
// Texts: locales/<language>.json, en.json is the source of all keys.
// The files are part of the bundle (no lazy loading): the UI works
// offline and starts without flicker.
//
// Non-React code (error texts, formatting, toasts) imports `i18n`
// directly and calls `i18n.t(...)`; components use `useTranslation()` so
// that they re-render when the language changes.

export const LANGUAGES = ["en", "de"] as const
export type Language = (typeof LANGUAGES)[number]

const STORAGE_KEY = "platform.language"
export const DEFAULT_LANGUAGE: Language = "en"

function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (LANGUAGES as readonly string[]).includes(value)
}

function storedLanguage(): Language {
  try {
    const value = globalThis.localStorage?.getItem(STORAGE_KEY)
    return isLanguage(value) ? value : DEFAULT_LANGUAGE
  } catch {
    return DEFAULT_LANGUAGE
  }
}

function applyToDocument(language: string) {
  if (typeof document !== "undefined") document.documentElement.lang = language
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, de: { translation: de } },
  lng: storedLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: LANGUAGES,
  // React escapes on its own; escaping twice would display "&amp;".
  interpolation: { escapeValue: false },
  // Resources are in the bundle -- initialize synchronously, no flicker.
  initAsync: false,
})
applyToDocument(i18n.language)
i18n.on("languageChanged", applyToDocument)

export function setLanguage(language: Language) {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, language)
  } catch {
    // without storage the choice only applies to this session
  }
  void i18n.changeLanguage(language)
}

export function useLanguage(): { language: Language; setLanguage: (language: Language) => void } {
  const { i18n: instance } = useTranslation()
  const language = isLanguage(instance.resolvedLanguage) ? instance.resolvedLanguage : DEFAULT_LANGUAGE
  return { language, setLanguage }
}

/**
 * Text for a key that is only known at runtime ("errors." + code) --
 * or undefined if it doesn't exist. Static keys go through the
 * type-checked `t("...")`.
 */
export function translateIfExists(key: string, options?: TOptions): string | undefined {
  if (!i18n.exists(key)) return undefined
  const text: unknown = i18n.t(key as never, options as never)
  return typeof text === "string" ? text : undefined
}

/**
 * Error whose text is only produced, in the current language, when displayed.
 * That way a visible error message follows along when the user switches the
 * language (describeError recognizes it).
 */
export class TranslatableError extends Error {
  readonly key: string
  readonly params?: TOptions

  constructor(key: string, params?: TOptions) {
    super(translateIfExists(key, params) ?? key)
    this.name = "TranslatableError"
    this.key = key
    this.params = params
  }

  translate(): string {
    return translateIfExists(this.key, this.params) ?? this.key
  }
}

export default i18n
