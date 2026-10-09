import { describe, expect, it } from "vitest"

import { aiState, type AiStatus } from "./queries"

const base: AiStatus = {
  provider: "ollama-cloud",
  url: "https://ollama.com",
  configured: true,
  reachable: true,
  checkedAt: 0,
  projects: { bds: { model: "gpt-oss:120b", available: true }, cra: { model: "gpt-oss:20b", available: true } },
}

describe("AI marker", () => {
  it("is ready only when every project's model exists", () => {
    expect(aiState(base)).toBe("ok")
    expect(aiState({ ...base, projects: { ...base.projects, cra: { model: "gone", available: false } } })).toBe(
      "model_missing",
    )
  })

  it("tells apart no key and no connection", () => {
    expect(aiState({ ...base, configured: false, reachable: false })).toBe("unconfigured")
    expect(aiState({ ...base, reachable: false })).toBe("unreachable")
  })
})
