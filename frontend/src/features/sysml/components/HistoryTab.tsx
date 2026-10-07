import { useQuery } from "@tanstack/react-query"
import { GitCommitHorizontal } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"

import { sysmlCommitsQuery } from "../queries"

type Props = {
  project: string
  /** Commit id of the snapshot being shown -- marked in the list. */
  current: string
}

/** "History" tab: the project's commits, newest first. Loads them itself, only when the tab is opened. */
export function HistoryTab({ project, current }: Props) {
  const { t, i18n } = useTranslation()
  const commits = useQuery(sysmlCommitsQuery(project))

  if (commits.isPending) return <Skeleton className="h-24" />
  if (commits.isError) return <p className="text-sm text-destructive">{describeError(commits.error)}</p>

  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">{t("sysml.history.title")}</CardTitle>
        <CardDescription className="text-xs">{t("sysml.history.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="px-4">
        <ol className="space-y-2 text-sm">
          {commits.data.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2">
              <GitCommitHorizontal className="size-4 text-muted-foreground" />
              <span className="font-mono text-xs" title={c.id}>
                {c.id.slice(0, 8)}
              </span>
              <span>{c.description || t("sysml.history.noDescription")}</span>
              {c.created && (
                <span className="text-xs text-muted-foreground">
                  {new Date(c.created).toLocaleString(i18n.language)}
                </span>
              )}
              {c.id === current && <Badge variant="secondary">{t("sysml.history.shown")}</Badge>}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
