import { useMutation } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"

// UI of the CRA group. Backend counterpart: backend/app/projects/cra/

type Match = { item_number: string; name: string; score: number }
type NearMiss = { item_number: string; name: string; failures: string[]; needs_tolerance_pct: number | null }
type SearchResult = {
  best: Match | null
  near_misses: NearMiss[]
  checked: number
  same_function: number
  passed: number
  tolerance_pct: number
}

const MAX_TOLERANCE = 30

/** "name = value" lines -> attributes; numbers stay numbers. */
export function parseAttributes(text: string): Record<string, string | number> {
  const attributes: Record<string, string | number> = {}
  for (const line of text.split("\n")) {
    const [name, ...rest] = line.split("=")
    const value = rest.join("=").trim()
    if (!name.trim() || !value) continue
    attributes[name.trim()] = value !== "" && !Number.isNaN(Number(value)) ? Number(value) : value
  }
  return attributes
}

export function CraPage() {
  const { t } = useTranslation()
  const [text, setText] = useState(t("cra.example"))
  const [tolerance, setTolerance] = useState(10)
  const search = useMutation({
    mutationFn: (pct: number) =>
      api<SearchResult>("/api/projects/cra/search", {
        method: "POST",
        body: { attributes: parseAttributes(text), tolerance_pct: pct },
      }),
  })
  const result = search.data

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="text-xl font-semibold">{t("cra.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("cra.hint")}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("cra.attributes")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={7}
            spellCheck={false}
            className="w-full rounded-md border border-input bg-transparent p-3 font-mono text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <div className="flex items-end gap-4">
            <div className="w-40 space-y-1">
              <Label htmlFor="cra-tolerance">{t("cra.tolerance")}</Label>
              <Input
                id="cra-tolerance"
                type="number"
                min={0}
                max={MAX_TOLERANCE}
                value={tolerance}
                onChange={(event) => setTolerance(Number(event.target.value))}
              />
            </div>
            <Button onClick={() => search.mutate(tolerance)} disabled={search.isPending}>
              <Search className="size-4" /> {search.isPending ? t("cra.searching") : t("cra.search")}
            </Button>
          </div>
          {search.isError && <p className="text-sm text-destructive">{search.error.message}</p>}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("cra.best")}</CardTitle>
            <CardDescription>
              {t("cra.stats", { checked: result.checked, same: result.same_function, passed: result.passed })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {result.best ? (
              <p>
                <span className="font-mono">{result.best.item_number}</span> – {result.best.name}{" "}
                <span className="text-sm text-muted-foreground">
                  ({t("cra.score")} {result.best.score})
                </span>
              </p>
            ) : (
              <p className="text-muted-foreground">{t("cra.none")}</p>
            )}
            {result.near_misses.length > 0 && (
              <div className="space-y-2">
                <h2 className="text-sm font-medium">{t("cra.nearMisses")}</h2>
                <ul className="space-y-2 text-sm">
                  {result.near_misses.map((miss) => (
                    <li key={miss.item_number + miss.name}>
                      <span className="font-mono">{miss.item_number}</span> – {miss.name}
                      <div className="text-muted-foreground">
                        {miss.failures.join("; ")} ·{" "}
                        {miss.needs_tolerance_pct === null ? (
                          t("cra.cannotFix")
                        ) : miss.needs_tolerance_pct <= MAX_TOLERANCE ? (
                          <button className="underline" onClick={() => search.mutate(miss.needs_tolerance_pct!)}>
                            {t("cra.retry", { pct: miss.needs_tolerance_pct })}
                          </button>
                        ) : (
                          t("cra.needs", { pct: miss.needs_tolerance_pct })
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
