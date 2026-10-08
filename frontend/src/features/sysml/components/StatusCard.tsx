import { useQuery } from "@tanstack/react-query"
import { CircleAlert, CircleCheck } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"

import { sysmlStatusQuery } from "../queries"

/** Is Flexo reachable? Green with the project count, or a hint how to start it. */
export function StatusCard() {
  const { t } = useTranslation()
  const status = useQuery(sysmlStatusQuery)

  if (status.isPending) return <Skeleton className="h-16" />
  if (status.isError) {
    return (
      <Card className="border-destructive/50 py-4">
        <CardContent className="flex items-center gap-3 px-4 text-sm">
          <CircleAlert className="size-5 text-destructive" />
          {describeError(status.error)}
        </CardContent>
      </Card>
    )
  }

  const s = status.data
  if (s.reachable) {
    return (
      <Card className="py-4">
        <CardContent className="flex flex-wrap items-center gap-3 px-4 text-sm">
          <CircleCheck className="size-5 text-success" />
          <span className="font-medium">{t("sysml.status.ok")}</span>
          <span className="text-muted-foreground">
            {t("sysml.status.projects", { count: s.projects ?? 0 })} · <span className="font-mono">{s.url}</span>
          </span>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card className="border-warning py-4">
      <CardContent className="space-y-2 px-4 text-sm">
        <p className="flex items-center gap-3 font-medium">
          <CircleAlert className="size-5 text-warning" />
          {t("sysml.status.down", { url: s.url })}
        </p>
        <p className="text-muted-foreground">{t("sysml.status.downHint")}</p>
        <code className="block w-fit rounded bg-muted px-2 py-1 text-xs">cd flexo &amp;&amp; docker compose up -d</code>
      </CardContent>
    </Card>
  )
}
