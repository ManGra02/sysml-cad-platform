import { useQuery } from "@tanstack/react-query"
import { Link, createFileRoute } from "@tanstack/react-router"
import { FileBox } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BridgeNotReady, useBridgeState } from "@/features/cad/components/ConnectionStatus"
import { describeError } from "@/features/cad/format"
import { documentsQuery } from "@/features/cad/queries"
import { useDocumentTitle } from "@/lib/useDocumentTitle"

export const Route = createFileRoute("/cad/")({
  component: DocumentsPage,
})

function DocumentsPage() {
  const { t } = useTranslation()
  const bridge = useBridgeState()
  const ready = bridge === "ok" || bridge === "busy"
  const query = useQuery({ ...documentsQuery, enabled: ready })
  useDocumentTitle(t("documents.pageTitle"), t("nav.cadExplorer"))

  if (!ready) return <BridgeNotReady state={bridge} />

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="mb-1 text-xl font-semibold">{t("documents.title")}</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        {t("documents.hint")}
      </p>

      {query.isPending && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      )}
      {query.isError && <p className="text-sm text-destructive">{describeError(query.error)}</p>}
      {query.data && query.data.documents.length === 0 && (
        <p className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
          {t("documents.empty")}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {query.data?.documents.map((doc) => (
          <Link key={doc.name} to="/cad/$doc" params={{ doc: doc.name }} className="block">
            <Card className="h-full gap-2 py-4 transition-colors hover:bg-muted/50">
              <CardHeader className="px-4">
                <CardTitle className="flex items-center gap-2">
                  <FileBox className="size-4 text-muted-foreground" />
                  <span className="truncate">{doc.label}</span>
                  {query.data.active === doc.name && <Badge variant="secondary">{t("common.active")}</Badge>}
                  {doc.modified && (
                    <Badge variant="outline" className="border-warning text-warning">
                      {t("documents.unsaved")}
                    </Badge>
                  )}
                </CardTitle>
                <CardDescription className="space-y-0.5 text-xs">
                  <p>
                    {t("documents.objects", { count: doc.objectCount })} · <span className="font-mono">{doc.name}</span>
                  </p>
                  <p className="truncate" title={doc.fileName ?? undefined}>
                    {doc.fileName ?? t("documents.neverSaved")}
                  </p>
                </CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
