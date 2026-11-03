import { Link } from "@tanstack/react-router"
import { ArrowRight } from "lucide-react"
import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import { useWorkspaceData } from "../context"
import { nextStep, type NextStep } from "../logic"

type AreaPath = "/projects/bds/$ws/assign" | "/projects/bds/$ws/check" | "/projects/bds/$ws/limits" | "/projects/bds/$ws/models"

/** Where each next step leads, and what its button says. */
const NEXT: Record<NextStep["kind"], { to: AreaPath; button: string }> = {
  empty: { to: "/projects/bds/$ws/models", button: "bds.models.title" },
  review: { to: "/projects/bds/$ws/assign", button: "bds.overview.review" },
  start: { to: "/projects/bds/$ws/assign", button: "bds.overview.toAssign" },
  offline: { to: "/projects/bds/$ws/check", button: "bds.overview.toCheck" },
  closed: { to: "/projects/bds/$ws/check", button: "bds.overview.toCheck" },
  check: { to: "/projects/bds/$ws/check", button: "bds.overview.toCheck" },
  recheck: { to: "/projects/bds/$ws/check", button: "bds.overview.toCheck" },
  violated: { to: "/projects/bds/$ws/check", button: "bds.overview.toResults" },
  unmeasured: { to: "/projects/bds/$ws/check", button: "bds.overview.toResults" },
  rest: { to: "/projects/bds/$ws/assign", button: "bds.overview.toAssign" },
  done: { to: "/projects/bds/$ws/limits", button: "bds.overview.toLimits" },
}

/**
 * The overview: what this workspace connects, the one next step (the page's only primary
 * button), then the three areas with where each stands. It does nothing itself -- it points.
 */
export function OverviewView() {
  const { t, i18n } = useTranslation()
  const data = useWorkspaceData()
  const { workspace, progress: p, pending, run, stale, bridgeDown, documentOpen } = data
  const step = nextStep(p, pending, { run: !!run, stale: !!stale, bridgeDown, documentOpen })
  const ws = workspace.name
  const when = run ? new Date(run.context.started_at).toLocaleString(i18n.language) : ""

  const title =
    step.kind === "empty"
      ? t("bds.overview.emptyTitle")
      : step.kind === "review"
        ? t("bds.overview.reviewTitle", { count: step.count })
        : step.kind === "violated"
          ? t("bds.overview.violatedTitle", { count: step.count })
          : step.kind === "unmeasured"
            ? t("bds.overview.unmeasuredTitle", { count: step.count })
          : step.kind === "rest"
            ? t("bds.overview.restTitle", { count: step.count })
            : t(`bds.overview.${step.kind}Title`)
  const text =
    step.kind === "empty"
      ? t("bds.table.empty")
      : step.kind === "offline"
        ? t("bds.banner.noBridgeNever")
        : step.kind === "closed"
          ? t("bds.banner.closed", { document: workspace.cad_document })
          : t(`bds.overview.${step.kind}Text`)

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        {t("bds.overview.intro", { project: workspace.sysml_project, document: workspace.cad_document || t("bds.page.noDocument") })}
      </p>

      <section aria-labelledby="bds-next" className="rounded-lg border-2 border-foreground/80 bg-card p-5">
        <p id="bds-next" className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          {t("bds.overview.next")}
        </p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0 flex-[1_1_24rem] space-y-1">
            <h2 className="text-lg font-semibold">{title}</h2>
            <p className="text-sm text-muted-foreground">{text}</p>
          </div>
          <Button asChild>
            <Link to={NEXT[step.kind].to} params={{ ws }} search={(s) => s}>
              {t(NEXT[step.kind].button as never)} <ArrowRight />
            </Link>
          </Button>
        </div>
      </section>

      <ol className="grid gap-4 md:grid-cols-3">
        <AreaCard
          n={1}
          ws={ws}
          to="/projects/bds/$ws/assign"
          title={t("bds.tabs.assign")}
          direction={t("bds.tabs.assignDir")}
          text={t("bds.overview.assignQ")}
          current={NEXT[step.kind].to === "/projects/bds/$ws/assign"}
        >
          {t("bds.overview.assignStatus", { assigned: p.assigned, total: p.total })}
          {pending > 0 && " · " + t("bds.overview.pending", { count: pending })}
        </AreaCard>
        <AreaCard
          n={2}
          ws={ws}
          to="/projects/bds/$ws/check"
          title={t("bds.tabs.check")}
          direction={t("bds.tabs.checkDir")}
          text={t("bds.overview.checkQ")}
          current={NEXT[step.kind].to === "/projects/bds/$ws/check"}
        >
          {run ? (
            <>
              {t("bds.list.summary", { passed: p.passed, tolerance: p.tolerance, violated: p.violated })}
              <span className="block text-xs text-muted-foreground">
                {t("bds.list.checkedAt", { when })}
                {(stale || p.unchecked > 0) && " · " + t("bds.tabs.stale")}
              </span>
            </>
          ) : (
            t("bds.overview.checkNever")
          )}
        </AreaCard>
        <AreaCard
          n={3}
          ws={ws}
          to="/projects/bds/$ws/limits"
          title={t("bds.tabs.limits")}
          direction={t("bds.tabs.limitsDir")}
          text={t("bds.overview.limitsQ")}
          current={NEXT[step.kind].to === "/projects/bds/$ws/limits"}
        >
          {t("bds.tabs.optional")}
        </AreaCard>
      </ol>


      {step.kind !== "empty" && (
        <p className="text-sm text-muted-foreground">
          <Link to="/projects/bds/$ws/models" params={{ ws }} search={(s) => s} className="underline underline-offset-4">
            {t("bds.overview.models")}
          </Link>
        </p>
      )}
    </div>
  )
}

function AreaCard({ n, ws, to, title, direction, text, current, children }: {
  n: number
  ws: string
  to: AreaPath
  title: string
  direction: string
  text: string
  /** The area the next step leads to. */
  current: boolean
  children: ReactNode
}) {
  const { t } = useTranslation()
  return (
    <li className={cn("flex flex-col gap-2 rounded-lg border bg-card p-4", current && "border-foreground/60")}>
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className={cn(
            "grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold",
            current ? "bg-foreground text-background" : "border text-muted-foreground",
          )}
        >
          {n}
        </span>
        <h3 className="font-semibold">{title}</h3>
        <span className="ml-auto text-xs text-muted-foreground">{direction}</span>
      </div>
      <p className="text-sm text-muted-foreground">{text}</p>
      <div className="mt-auto pt-1 text-sm font-medium">{children}</div>
      <Link to={to} params={{ ws }} search={(s) => s} className="w-fit text-sm underline underline-offset-4">
        {t("bds.overview.open")} <span className="sr-only">{title}</span>
      </Link>
    </li>
  )
}
