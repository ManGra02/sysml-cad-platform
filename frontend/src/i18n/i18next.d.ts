import "i18next"

import type en from "./locales/en.json"

// Type-safe keys: t("explorer.recompute") is checked against en.json, so
// typos show up in the typecheck. That de.json is complete is checked by
// i18n.test.ts (keys and placeholders).
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation"
    resources: { translation: typeof en }
  }
}
