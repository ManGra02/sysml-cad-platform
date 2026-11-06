import { useMutation } from "@tanstack/react-query"
import { Bot, Box, ListChecks, TriangleAlert } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"

// UI of the CRA group. Backend counterpart: backend/app/projects/cra/

type Outcome = "reuse" | "cad_found" | "envelope_proposed" | "nothing_suitable" | "answer"
type CraResult = {
  mission: string
  subject: string
  understanding: string
  outcome: Outcome
  item_number: string | null
  name: string | null
  cad_file: string | null
  confidence: "high" | "medium" | "low"
  evidence: string[]
  plm_issues: string[]
  relaxed_rules: string[]
  open_questions: string[]
}
type Step = { tool: string; args: Record<string, unknown>; result?: string }
type AgentRun = { model: string; answer: string; steps: Step[]; result?: CraResult }
type MissingCad = { count: number; parts: Array<{ item_number: string; name: string; kind: string }> }
type Envelope = { type: string; props: Record<string, string>; label: string; basis: string }

/** The envelope the agent proposed, if any -- taken from its tool results, not from its text. */
export function proposedEnvelope(steps: Step[]): Envelope | null {
  for (const step of [...steps].reverse()) {
    if (step.tool !== "propose_envelope_model" || !step.result) continue
    try {
      const value = JSON.parse(step.result) as Partial<Envelope>
      if (value.type && value.props) return value as Envelope
    } catch {
      // truncated or an error: no proposal
    }
  }
  return null
}

function List({ title, items, warn }: { title: string; items: string[]; warn?: boolean }) {
  if (items.length === 0) return null
  return (
    <div className="space-y-1">
      <h3 className={"flex items-center gap-1 text-sm font-medium" + (warn ? " text-destructive" : "")}>
        {warn && <TriangleAlert className="size-4" />} {title}
      </h3>
      <ul className="list-disc space-y-0.5 pl-5 text-sm">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

export function CraPage() {
  const { t } = useTranslation()
  const [message, setMessage] = useState("")
  const [last, setLast] = useState<"ask" | "cad">("ask")
  const ask = useMutation({
    mutationFn: (text: string) => api<AgentRun>("/api/projects/cra/agent", { method: "POST", body: { message: text } }),
  })
  const findCad = useMutation({
    mutationFn: (itemNumber: string) =>
      api<AgentRun>("/api/projects/cra/find-cad", { method: "POST", body: { item_number: itemNumber } }),
  })
  const missing = useMutation({ mutationFn: () => api<MissingCad>("/api/projects/cra/plm/missing-cad") })
  const create = useMutation({
    mutationFn: (envelope: Envelope) =>
      api<{ doc: string; name: string }>("/api/projects/cra/envelope", { method: "POST", body: envelope }),
  })

  const latest = last === "ask" ? ask : findCad
  const busy = ask.isPending || findCad.isPending
  const run = latest.data
  const result = run?.result
  const envelope = run ? proposedEnvelope(run.steps) : null

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Bot className="size-5" /> {t("cra.title")}
        </h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("cra.askTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={3}
            placeholder={t("cra.askPlaceholder")}
            className="w-full rounded-md border border-input bg-transparent p-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <Button onClick={() => {
              setLast("ask")
              ask.mutate(message)
            }} disabled={busy || !message.trim()}>
            {busy ? t("cra.running") : t("cra.run")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">{t("cra.missingTitle")}</CardTitle>
          <Button variant="outline" size="sm" onClick={() => missing.mutate()} disabled={missing.isPending}>
            {t("cra.load")}
          </Button>
        </CardHeader>
        {(missing.data || missing.isError) && (
          <CardContent>
            {missing.isError && <p className="text-sm text-destructive">{missing.error.message}</p>}
            {missing.data?.count === 0 && <p className="text-sm text-muted-foreground">{t("cra.noneMissing")}</p>}
            <ul className="max-h-72 space-y-1 overflow-y-auto text-sm">
              {missing.data?.parts.map((part) => (
                <li key={part.item_number} className="flex items-center gap-3">
                  {part.item_number !== part.name && (
                    <span className="w-28 shrink-0 truncate font-mono" title={part.item_number}>
                      {part.item_number}
                    </span>
                  )}
                  <span className="flex-1">{part.name}</span>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => {
                      setLast("cad")
                      findCad.mutate(part.item_number)
                    }}>
                    {t("cra.findCad")}
                  </Button>
                </li>
              ))}
            </ul>
          </CardContent>
        )}
      </Card>

      {busy && <p className="text-sm text-muted-foreground">{t("cra.running")}</p>}
      {latest.isError && <p className="text-sm text-destructive">{latest.error.message}</p>}

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2 text-base">
              {t("cra.resultTitle")}
              <Badge>{t(`cra.outcome.${result.outcome}`)}</Badge>
              <Badge variant="secondary">{t("cra.confidence", { level: result.confidence })}</Badge>
            </CardTitle>
            {result.subject && <CardDescription className="font-mono">{result.subject}</CardDescription>}
          </CardHeader>
          <CardContent className="space-y-4">
            {result.understanding && (
              <p className="text-sm">
                <span className="text-muted-foreground">{t("cra.understanding")}:</span> {result.understanding}
              </p>
            )}
            {result.item_number && (
              <p>
                <span className="text-sm text-muted-foreground">{t("cra.recommended")}:</span>{" "}
                <span className="font-mono">{result.item_number}</span> – {result.name}
                {result.cad_file && <span className="text-sm text-muted-foreground"> ({result.cad_file})</span>}
              </p>
            )}
            <List title={t("cra.evidence")} items={result.evidence} />
            <List title={t("cra.plmIssues")} items={result.plm_issues} warn />
            <List title={t("cra.relaxed")} items={result.relaxed_rules} />
            <List title={t("cra.openQuestions")} items={result.open_questions} />
            {envelope && (
              <div className="flex flex-wrap items-center gap-3 rounded-md border p-3 text-sm">
                <Box className="size-4" /> {t("cra.envelope", { basis: envelope.basis })}
                <Button size="sm" onClick={() => create.mutate(envelope)} disabled={create.isPending || create.isSuccess}>
                  {t("cra.createEnvelope")}
                </Button>
                {create.data && <span>{t("cra.envelopeCreated", create.data)}</span>}
                {create.isError && <span className="text-destructive">{create.error.message}</span>}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {run && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ListChecks className="size-4" /> {t("cra.stepsTitle", { count: run.steps.length })}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <ol className="list-decimal space-y-1 pl-5 font-mono text-xs">
              {run.steps.map((step, index) => (
                <li key={index}>
                  <span className="font-semibold">{step.tool}</span> {JSON.stringify(step.args)}
                </li>
              ))}
            </ol>
            <div className="space-y-1">
              <h3 className="text-sm font-medium">{t("cra.answer")}</h3>
              <p className="whitespace-pre-wrap text-sm">{run.answer}</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
