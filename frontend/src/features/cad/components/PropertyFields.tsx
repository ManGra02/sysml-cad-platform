import { ArrowUpRight, Check, Loader2 } from "lucide-react"
import { useEffect, useRef, useState, type FocusEvent, type KeyboardEvent, type ReactNode } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { TranslatableError } from "@/i18n"
import { cn } from "@/lib/utils"
import type { CommitOutcome } from "../editing"
import { describeError, formatNumber, formatValue, parseNumber } from "../format"
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

// One field per property, chosen by the VALUE (not by the CAD type):
// the editor knows neither Part::Box nor PartDesign::Pad.
//
// Commit on blur or Enter, never per keystroke -- FreeCAD's undo stack holds
// only 20 entries. Escape discards. Compound values (placement, vector) are
// only sent as one value when the WHOLE group is left.

export type FieldContext = {
  begin: (entry: PropertyEntry) => void
  cancel: (prop: string) => void
  commit: (entry: PropertyEntry, payload: unknown, display: string) => Promise<CommitOutcome>
  labels: Record<string, string>
  objects: TreeNode[]
  self: string
  navigate: (name: string) => void
}

// Errors are stored as the CAUSE, not as text: FieldShell builds the text at
// display time (describeError), so it follows along when the language changes.
type FieldError = unknown
type Parsed = { payload: unknown } | { error: FieldError }

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
  const { t } = useTranslation()
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
            if (number === null) return { error: new TranslatableError("fields.numberExpected") }
            if (kind === "int" && !Number.isInteger(number)) return { error: new TranslatableError("fields.integerExpected") }
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
          hint={quantity.unitType ? t(("unitTypes." + quantity.unitType) as never, { defaultValue: quantity.unitType }) : undefined}
          parse={(text) => {
            // "12,5 mm" -> "12.5 mm": FreeCAD's parser expects the dot.
            const normalized = text.trim().replace(/(\d),(\d)/g, "$1.$2")
            if (!normalized) return { error: new TranslatableError("fields.valueExpected") }
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
      return <Muted>{t("fields.derived")}</Muted>
    case "unsupported": {
      const value = entry.value as { summary?: string } | null
      return <Muted title={entry.typeId}>{t("fields.unsupported")}{value?.summary ? " · " + value.summary : ""}</Muted>
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

// -- Simple fields ---------------------------------------------------------

const SAVED_MS = 1200

/** Result of a commit as a field error -- null on success or deliberate discard. */
function failure(outcome: CommitOutcome): FieldError | null {
  if (outcome.ok || outcome.discarded) return null
  return outcome.error ?? new TranslatableError("common.error")
}

function useCommitState() {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<FieldError | null>(null)
  const [saved, setSaved] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  /** After the commit: remove the loading indicator; on success briefly show a checkmark ("applied"). */
  const settle = (outcome: CommitOutcome) => {
    setPending(false)
    if (!outcome.ok) return
    setSaved(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setSaved(false), SAVED_MS)
  }
  return { pending, setPending, error, setError, saved, settle }
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
  const { pending, setPending, error, setError, saved, settle } = useCommitState()
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
    settle(outcome)
    if (outcome.ok || outcome.discarded) {
      setDraft(null)
      setError(null)
    } else {
      setError(outcome.error ?? new TranslatableError("common.error"))
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      // preventDefault: otherwise the same Enter key "clicks" the button that
      // a conflict dialog, if one opens, puts the focus on.
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
    <FieldShell pending={pending} saved={saved} error={error}>
      <Input
        value={draft ?? value}
        inputMode={inputMode}
        disabled={pending}
        title={hint}
        aria-invalid={error != null ? true : undefined}
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

function FieldShell({
  pending,
  saved,
  error,
  children,
}: {
  pending: boolean
  saved: boolean
  error: FieldError | null
  children: ReactNode
}) {
  const { t } = useTranslation()
  return (
    <div className="min-w-0">
      <div className="relative">
        {children}
        {pending && <Loader2 className="absolute top-1.5 right-2 size-4 animate-spin text-muted-foreground" />}
        {!pending && saved && (
          <Check
            className="absolute top-1.5 right-2 size-4 text-success animate-in fade-in zoom-in-50"
            aria-hidden
          />
        )}
      </div>
      <span className="sr-only" aria-live="polite">
        {saved ? t("fields.saved") : ""}
      </span>
      {error != null && <p className="mt-0.5 text-xs text-destructive">{describeError(error)}</p>}
    </div>
  )
}

function BoolField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const { t } = useTranslation()
  const { pending, setPending, error, setError, saved, settle } = useCommitState()
  const [optimistic, setOptimistic] = useState<boolean | null>(null)
  return (
    <FieldShell pending={pending} saved={saved} error={error}>
      <div className="flex h-7 items-center">
        <Switch
          checked={optimistic ?? (entry.value as boolean)}
          disabled={pending}
          onCheckedChange={async (checked) => {
            ctx.begin(entry)
            setOptimistic(checked)
            setPending(true)
            const outcome = await ctx.commit(entry, checked, checked ? t("common.yes") : t("common.no"))
            settle(outcome)
            setOptimistic(null)
            setError(failure(outcome))
          }}
        />
      </div>
    </FieldShell>
  )
}

function EnumField({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const value = entry.value as EnumValue
  const { pending, setPending, error, setError, saved, settle } = useCommitState()
  return (
    <FieldShell pending={pending} saved={saved} error={error}>
      <Select
        value={String(value.value)}
        disabled={pending}
        onValueChange={async (choice) => {
          ctx.begin(entry)
          setPending(true)
          const outcome = await ctx.commit(entry, choice, choice)
          settle(outcome)
          setError(failure(outcome))
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
  const { t } = useTranslation()
  const value = entry.value as LinkValue
  const { pending, setPending, error, setError, saved, settle } = useCommitState()
  const target = value.ref?.name
  const sameDoc = !value.ref?.doc || ctx.objects.some((node) => node.doc === value.ref?.doc)
  const candidates = ctx.objects.filter((node) => node.name !== ctx.self && !node.internal)

  return (
    <FieldShell pending={pending} saved={saved} error={error}>
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
            settle(outcome)
            setError(failure(outcome))
          }}
        >
          <SelectTrigger size="sm" className="h-7 min-w-0 flex-1 text-xs">
            <SelectValue placeholder="—" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_LINK} className="text-xs text-muted-foreground">
              {t("fields.noLink")}
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
          <Button variant="ghost" size="icon-xs" title={t("fields.toLinked")} onClick={() => ctx.navigate(target)}>
            <ArrowUpRight />
          </Button>
        )}
      </div>
    </FieldShell>
  )
}

// -- Compound fields ---------------------------------------------------------

function useCompound(entry: PropertyEntry, ctx: FieldContext, initial: () => string[]) {
  const [draft, setDraft] = useState<string[] | null>(null)
  const { pending, setPending, error, setError, saved, settle } = useCommitState()
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
      setError(new TranslatableError("fields.numbersExpected"))
      return
    }
    let built: { payload: unknown; display: string }
    try {
      built = build(numbers as number[], original)
    } catch (buildError) {
      setError(buildError)
      return
    }
    setPending(true)
    const outcome = await ctx.commit(entry, built.payload, built.display)
    settle(outcome)
    if (outcome.ok || outcome.discarded) {
      setDraft(null)
      setError(null)
    } else {
      setError(outcome.error ?? new TranslatableError("common.error"))
    }
  }

  const containerProps = (build: Parameters<typeof finish>[0]) => ({
    onFocus: start,
    onBlur: (event: FocusEvent<HTMLDivElement>) => {
      // A focus change WITHIN the group is not a commit.
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

  return { values, pending, saved, error, containerProps, setPart, dirty: draft !== null }
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
    <FieldShell pending={field.pending} saved={field.saved} error={field.error}>
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
  const { t } = useTranslation()
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
    // Only recompute the rotation if it was touched -- otherwise rounding
    // the axis would produce a spurious change in FreeCAD.
    const rotationTouched = field.values.slice(3).some((part, index) => part !== original[3 + index])
    const q = rotationTouched
      ? axisAngleToQuat([numbers[3], numbers[4], numbers[5]], numbers[6])
      : placement.q
    const payload: PlacementValue = { kind: "placement", pos, q }
    return { payload, display: formatValue(payload) }
  }

  return (
    <FieldShell pending={field.pending} saved={field.saved} error={field.error}>
      <div className="space-y-1" {...field.containerProps(build)}>
        <p className="text-[10px] text-muted-foreground">{t("fields.position")}</p>
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
        <p className="text-[10px] text-muted-foreground">{t("fields.axisAngle")}</p>
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

// -- Read-only ---------------------------------------------------------------

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
