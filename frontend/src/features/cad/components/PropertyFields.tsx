import { ArrowUpRight, Loader2 } from "lucide-react"
import { useRef, useState, type FocusEvent, type KeyboardEvent, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import type { CommitOutcome } from "../editing"
import { formatNumber, formatValue, parseNumber } from "../format"
import { axisAngleToQuat, quatToAxisAngle } from "../rotation"
import type {
  EnumValue,
  LinkValue,
  ObjRef,
  PlacementValue,
  PropertyEntry,
  Quantity,
  TreeNode,
  VectorValue,
} from "../types"

// Ein Feld pro Property, gewaehlt nach dem WERT (nicht nach dem CAD-Typ):
// der Editor kennt weder Part::Box noch PartDesign::Pad.
//
// Commit auf Blur oder Enter, nie pro Tastendruck -- FreeCADs Undo-Stack haelt
// nur 20 Eintraege. Escape verwirft. Zusammengesetzte Werte (Lage, Vektor)
// werden erst beim Verlassen der GANZEN Gruppe als ein Wert gesendet.

export type FieldContext = {
  begin: (entry: PropertyEntry) => void
  cancel: (prop: string) => void
  commit: (entry: PropertyEntry, payload: unknown, display: string) => Promise<CommitOutcome>
  labels: Record<string, string>
  objects: TreeNode[]
  self: string
  navigate: (name: string) => void
}

type Parsed = { payload: unknown } | { error: string }

export type FieldKind =
  | "bool"
  | "int"
  | "float"
  | "text"
  | "quantity"
  | "enum"
  | "placement"
  | "vector"
  | "link"
  | "readonly"
  | "derived"
  | "unsupported"

const INTEGER_TYPES = /Integer|Percent/

export function fieldKind(entry: PropertyEntry): FieldKind {
  if (entry.status === "unsupported") return "unsupported"
  if (entry.status === "derived") return "derived"
  if (!entry.writable || entry.expression) return "readonly"
  const value = entry.value
  if (typeof value === "boolean") return "bool"
  if (typeof value === "number") return INTEGER_TYPES.test(entry.typeId) ? "int" : "float"
  if (typeof value === "string") return "text"
  if (value && !Array.isArray(value) && typeof value === "object") {
    switch (value.kind) {
      case "quantity":
      case "enum":
      case "placement":
      case "vector":
      case "link":
        return value.kind
    }
  }
  return "readonly"
}

export function PropertyField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const kind = fieldKind(entry)
  switch (kind) {
    case "bool":
      return <BoolField entry={entry} ctx={ctx} />
    case "int":
    case "float":
      return (
        <TextField
          entry={entry}
          ctx={ctx}
          value={formatNumber(entry.value as number, 9)}
          inputMode="decimal"
          parse={(text) => {
            const number = parseNumber(text)
            if (number === null) return { error: "Zahl erwartet" }
            if (kind === "int" && !Number.isInteger(number)) return { error: "Ganzzahl erwartet" }
            return { payload: number }
          }}
        />
      )
    case "text":
      return <TextField entry={entry} ctx={ctx} value={entry.value as string} parse={(text) => ({ payload: text })} />
    case "quantity": {
      const quantity = entry.value as Quantity
      return (
        <TextField
          entry={entry}
          ctx={ctx}
          value={quantity.text}
          hint={quantity.unitType ?? undefined}
          parse={(text) => {
            // "12,5 mm" -> "12.5 mm": FreeCADs Parser erwartet den Punkt.
            const normalized = text.trim().replace(/(\d),(\d)/g, "$1.$2")
            if (!normalized) return { error: "Wert erwartet" }
            return { payload: normalized }
          }}
        />
      )
    }
    case "enum":
      return <EnumField entry={entry} ctx={ctx} />
    case "placement":
      return <PlacementField entry={entry} ctx={ctx} />
    case "vector":
      return <VectorField entry={entry} ctx={ctx} />
    case "link":
      return <LinkField entry={entry} ctx={ctx} />
    case "derived":
      return <Muted>abgeleitet – siehe Geometrie</Muted>
    case "unsupported": {
      const value = entry.value as { summary?: string } | null
      return <Muted title={entry.typeId}>vorhanden, hier nicht darstellbar{value?.summary ? " · " + value.summary : ""}</Muted>
    }
    default:
      return <ReadOnlyValue entry={entry} ctx={ctx} />
  }
}

function Muted({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span title={title} className="block truncate py-1 text-xs italic text-muted-foreground">
      {children}
    </span>
  )
}

// -- Einfache Felder -------------------------------------------------------

function useCommitState() {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return { pending, setPending, error, setError }
}

function TextField({
  entry,
  ctx,
  value,
  parse,
  hint,
  inputMode,
}: {
  entry: PropertyEntry
  ctx: FieldContext
  value: string
  parse: (text: string) => Parsed
  hint?: string
  inputMode?: "decimal" | "text"
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const { pending, setPending, error, setError } = useCommitState()
  const skip = useRef(false)

  const finish = async () => {
    if (skip.current) {
      skip.current = false
      return
    }
    if (draft === null) return
    if (draft === value) {
      setDraft(null)
      setError(null)
      ctx.cancel(entry.name)
      return
    }
    const parsed = parse(draft)
    if ("error" in parsed) {
      setError(parsed.error)
      return
    }
    setPending(true)
    const outcome = await ctx.commit(entry, parsed.payload, draft)
    setPending(false)
    if (outcome.ok || outcome.discarded) {
      setDraft(null)
      setError(null)
    } else {
      setError(outcome.message ?? "Fehler")
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      // preventDefault: sonst "klickt" dieselbe Enter-Taste den Knopf, auf
      // den ein ggf. aufgehender Konfliktdialog den Fokus legt.
      event.preventDefault()
      event.currentTarget.blur()
    }
    if (event.key === "Escape") {
      skip.current = true
      setDraft(null)
      setError(null)
      ctx.cancel(entry.name)
      event.currentTarget.blur()
    }
  }

  return (
    <FieldShell pending={pending} error={error}>
      <Input
        value={draft ?? value}
        inputMode={inputMode}
        disabled={pending}
        title={hint}
        aria-invalid={error ? true : undefined}
        className={cn("h-7 px-2 font-mono text-xs", draft !== null && draft !== value && "border-warning")}
        onFocus={() => {
          if (draft === null) {
            setDraft(value)
            ctx.begin(entry)
          }
        }}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void finish()}
        onKeyDown={onKeyDown}
      />
    </FieldShell>
  )
}

function FieldShell({ pending, error, children }: { pending: boolean; error: string | null; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="relative">
        {children}
        {pending && <Loader2 className="absolute top-1.5 right-2 size-4 animate-spin text-muted-foreground" />}
      </div>
      {error && <p className="mt-0.5 text-xs text-destructive">{error}</p>}
    </div>
  )
}

function BoolField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const { pending, setPending, error, setError } = useCommitState()
  const [optimistic, setOptimistic] = useState<boolean | null>(null)
  return (
    <FieldShell pending={pending} error={error}>
      <div className="flex h-7 items-center">
        <Switch
          checked={optimistic ?? (entry.value as boolean)}
          disabled={pending}
          onCheckedChange={async (checked) => {
            ctx.begin(entry)
            setOptimistic(checked)
            setPending(true)
            const outcome = await ctx.commit(entry, checked, checked ? "ja" : "nein")
            setPending(false)
            setOptimistic(null)
            setError(outcome.ok || outcome.discarded ? null : (outcome.message ?? "Fehler"))
          }}
        />
      </div>
    </FieldShell>
  )
}

function EnumField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const value = entry.value as EnumValue
  const { pending, setPending, error, setError } = useCommitState()
  return (
    <FieldShell pending={pending} error={error}>
      <Select
        value={String(value.value)}
        disabled={pending}
        onValueChange={async (choice) => {
          ctx.begin(entry)
          setPending(true)
          const outcome = await ctx.commit(entry, choice, choice)
          setPending(false)
          setError(outcome.ok || outcome.discarded ? null : (outcome.message ?? "Fehler"))
        }}
      >
        <SelectTrigger size="sm" className="h-7 w-full text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {value.choices.map((choice) => (
            <SelectItem key={choice} value={choice} className="text-xs">
              {choice}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FieldShell>
  )
}

const NO_LINK = "__none__"

function LinkField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const value = entry.value as LinkValue
  const { pending, setPending, error, setError } = useCommitState()
  const target = value.ref?.name
  const sameDoc = !value.ref?.doc || ctx.objects.some((node) => node.doc === value.ref?.doc)
  const candidates = ctx.objects.filter((node) => node.name !== ctx.self && !node.internal)

  return (
    <FieldShell pending={pending} error={error}>
      <div className="flex items-center gap-1">
        <Select
          value={target ?? NO_LINK}
          disabled={pending || !sameDoc}
          onValueChange={async (choice) => {
            ctx.begin(entry)
            const doc = ctx.objects[0]?.doc
            const ref: ObjRef | null = choice === NO_LINK || !doc ? null : { doc, name: choice }
            setPending(true)
            const outcome = await ctx.commit(entry, { kind: "link", ref }, ref ? (ctx.labels[choice] ?? choice) : "—")
            setPending(false)
            setError(outcome.ok || outcome.discarded ? null : (outcome.message ?? "Fehler"))
          }}
        >
          <SelectTrigger size="sm" className="h-7 min-w-0 flex-1 text-xs">
            <SelectValue placeholder="—" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_LINK} className="text-xs text-muted-foreground">
              — keine Verknüpfung —
            </SelectItem>
            {target && !candidates.some((node) => node.name === target) && (
              <SelectItem value={target} className="text-xs">
                {ctx.labels[target] ?? target}
              </SelectItem>
            )}
            {candidates.map((node) => (
              <SelectItem key={node.name} value={node.name} className="text-xs">
                {node.label}
                {node.label !== node.name && <span className="text-muted-foreground"> ({node.name})</span>}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {target && sameDoc && (
          <Button variant="ghost" size="icon-xs" title="Zum verknüpften Objekt" onClick={() => ctx.navigate(target)}>
            <ArrowUpRight />
          </Button>
        )}
      </div>
    </FieldShell>
  )
}

// -- Zusammengesetzte Felder -------------------------------------------------

function useCompound(entry: PropertyEntry, ctx: FieldContext, initial: () => string[]) {
  const [draft, setDraft] = useState<string[] | null>(null)
  const { pending, setPending, error, setError } = useCommitState()
  const skip = useRef(false)
  const values = draft ?? initial()

  const start = () => {
    if (draft === null) {
      setDraft(initial())
      ctx.begin(entry)
    }
  }

  const reset = () => {
    setDraft(null)
    setError(null)
    ctx.cancel(entry.name)
  }

  const finish = async (build: (parts: number[], original: string[]) => { payload: unknown; display: string }) => {
    if (skip.current) {
      skip.current = false
      return
    }
    if (draft === null) return
    const original = initial()
    if (draft.every((part, index) => part === original[index])) return reset()
    const numbers = draft.map(parseNumber)
    if (numbers.some((number) => number === null)) {
      setError("Zahlen erwartet")
      return
    }
    let built: { payload: unknown; display: string }
    try {
      built = build(numbers as number[], original)
    } catch (buildError) {
      setError((buildError as Error).message)
      return
    }
    setPending(true)
    const outcome = await ctx.commit(entry, built.payload, built.display)
    setPending(false)
    if (outcome.ok || outcome.discarded) {
      setDraft(null)
      setError(null)
    } else {
      setError(outcome.message ?? "Fehler")
    }
  }

  const containerProps = (build: Parameters<typeof finish>[0]) => ({
    onFocus: start,
    onBlur: (event: FocusEvent<HTMLDivElement>) => {
      // Fokuswechsel INNERHALB der Gruppe ist kein Commit.
      if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
      void finish(build)
    },
    onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Enter") {
        event.preventDefault()
        ;(event.target as HTMLElement).blur()
      }
      if (event.key === "Escape") {
        skip.current = true
        reset()
        ;(event.target as HTMLElement).blur()
      }
    },
  })

  const setPart = (index: number, text: string) =>
    setDraft((old) => {
      const next = [...(old ?? initial())]
      next[index] = text
      return next
    })

  return { values, pending, error, containerProps, setPart, dirty: draft !== null }
}

function NumberCell({
  label,
  value,
  onChange,
  disabled,
  suffix,
}: {
  label: string
  value: string
  onChange: (text: string) => void
  disabled: boolean
  suffix?: string
}) {
  return (
    <label className="flex min-w-0 items-center gap-1">
      <span className="w-3 shrink-0 text-[10px] text-muted-foreground uppercase">{label}</span>
      <Input
        value={value}
        inputMode="decimal"
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="h-7 min-w-0 px-1.5 font-mono text-xs"
      />
      {suffix && <span className="shrink-0 text-[10px] text-muted-foreground">{suffix}</span>}
    </label>
  )
}

function VectorField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const vector = entry.value as VectorValue
  const field = useCompound(entry, ctx, () => [vector.x, vector.y, vector.z].map((n) => formatNumber(n, 9)))
  const build = ([x, y, z]: number[]) => ({
    payload: { kind: "vector", x, y, z },
    display: "(" + [x, y, z].map((n) => formatNumber(n)).join(", ") + ")",
  })
  return (
    <FieldShell pending={field.pending} error={field.error}>
      <div className="grid grid-cols-3 gap-1" {...field.containerProps(build)}>
        {["x", "y", "z"].map((axis, index) => (
          <NumberCell
            key={axis}
            label={axis}
            value={field.values[index]}
            disabled={field.pending}
            onChange={(text) => field.setPart(index, text)}
          />
        ))}
      </div>
    </FieldShell>
  )
}

function PlacementField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const placement = entry.value as PlacementValue
  const initial = () => {
    const { axis, angle } = quatToAxisAngle(placement.q)
    return [
      ...placement.pos.map((n) => formatNumber(n, 9)),
      ...axis.map((n) => formatNumber(n, 9)),
      formatNumber(angle, 9),
    ]
  }
  const field = useCompound(entry, ctx, initial)

  const build = (numbers: number[], original: string[]) => {
    const pos = numbers.slice(0, 3)
    // Drehung nur neu berechnen, wenn sie angefasst wurde -- sonst erzeugte
    // die Rundung der Achse eine Scheinaenderung in FreeCAD.
    const rotationTouched = field.values.slice(3).some((part, index) => part !== original[3 + index])
    const q = rotationTouched
      ? axisAngleToQuat([numbers[3], numbers[4], numbers[5]], numbers[6])
      : placement.q
    const payload: PlacementValue = { kind: "placement", pos, q }
    return { payload, display: formatValue(payload) }
  }

  return (
    <FieldShell pending={field.pending} error={field.error}>
      <div className="space-y-1" {...field.containerProps(build)}>
        <p className="text-[10px] text-muted-foreground">Position</p>
        <div className="grid grid-cols-3 gap-1">
          {["x", "y", "z"].map((axis, index) => (
            <NumberCell
              key={axis}
              label={axis}
              value={field.values[index]}
              disabled={field.pending}
              onChange={(text) => field.setPart(index, text)}
            />
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground">Drehachse und Winkel</p>
        <div className="grid grid-cols-4 gap-1">
          {["ax", "ay", "az"].map((axis, index) => (
            <NumberCell
              key={axis}
              label={axis.slice(1)}
              value={field.values[3 + index]}
              disabled={field.pending}
              onChange={(text) => field.setPart(3 + index, text)}
            />
          ))}
          <NumberCell
            label="∠"
            suffix="°"
            value={field.values[6]}
            disabled={field.pending}
            onChange={(text) => field.setPart(6, text)}
          />
        </div>
      </div>
    </FieldShell>
  )
}

// -- Nur lesen ---------------------------------------------------------------

function ReadOnlyValue({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const value = entry.value
  if (value && typeof value === "object" && !Array.isArray(value)) {
    if (value.kind === "color") {
      const [r, g, b, a] = value.rgba
      return (
        <span className="flex items-center gap-2 py-1 text-xs">
          <span
            className="inline-block size-3.5 rounded-sm border"
            style={{ background: "rgba(" + [r * 255, g * 255, b * 255, a ?? 1].join(",") + ")" }}
          />
          <span className="font-mono text-muted-foreground">{formatValue(value)}</span>
        </span>
      )
    }
    const refs =
      value.kind === "link" || value.kind === "link_sub"
        ? value.ref
          ? [value.ref]
          : []
        : value.kind === "link_list" || value.kind === "link_sub_list"
          ? value.refs
          : null
    if (refs) {
      if (!refs.length) return <span className="block py-1 text-xs text-muted-foreground">—</span>
      return (
        <span className="flex flex-wrap gap-1 py-0.5">
          {refs.map((ref, index) => (
            <button
              key={index}
              type="button"
              className="rounded border px-1.5 py-0.5 text-xs hover:bg-accent"
              title={ref.doc + " · " + ref.name}
              onClick={() => ctx.navigate(ref.name)}
            >
              {ctx.labels[ref.name] ?? ref.name}
              {ref.subs?.length ? <span className="text-muted-foreground"> · {ref.subs.join(", ")}</span> : null}
            </button>
          ))}
        </span>
      )
    }
  }
  return (
    <span className="block truncate py-1 font-mono text-xs text-muted-foreground" title={formatValue(value, ctx.labels)}>
      {formatValue(value, ctx.labels)}
    </span>
  )
}
