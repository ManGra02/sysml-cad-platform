import { queryOptions, useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Radio } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api, seg } from "@/lib/api"
import { ProjectIcon } from "./ProjectIcon"
import { projectKeys, projectsQuery } from "./queries"

type StubInfo = {
  id: string
  stub: boolean
  activeSince: number | null
  eventsSeen: number
  recent: Array<{ type: string; doc?: string; obj?: string; props?: string[]; origin?: string; at: number }>
}

const infoQuery = (id: string) =>
  queryOptions({
    queryKey: [...projectKeys.module(id), "info"],
    queryFn: () => api<StubInfo>("/api/projects/" + seg(id) + "/info"),
  })

/**
 * Platzhalterseite eines Projekts. Zeigt, dass die Verdrahtung steht:
 * FreeCAD -> Bruecke -> Backend -> Modul (on_cad_event) -> Browser.
 * Wird ersetzt, sobald die Gruppe ihre eigene Oberflaeche baut.
 */
export function ProjectStub({ id }: { id: string }) {
  const projects = useQuery(projectsQuery)
  const info = useQuery(infoQuery(id))
  const project = projects.data?.projects.find((entry) => entry.id === id)

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="flex items-start gap-4">
        <div className="grid size-12 shrink-0 place-items-center rounded-lg bg-muted">
          <ProjectIcon name={project?.icon ?? "boxes"} className="size-6" />
        </div>
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            {project?.title ?? id}
            <Badge variant="secondary">Platzhalter</Badge>
          </h1>
          <p className="text-sm text-muted-foreground">{project?.description}</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Radio className="size-4" /> Ereignisse aus FreeCAD
          </CardTitle>
          <CardDescription>
            Was das Modul seit seiner Aktivierung über <code>on_cad_event</code> bekommen hat. Ändere etwas in FreeCAD
            oder im <Link to="/cad" className="underline">CAD-Explorer</Link> – die Liste aktualisiert sich live.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-2xl font-semibold tabular-nums">{info.data?.eventsSeen ?? "–"}</p>
          <ul className="space-y-1 font-mono text-xs">
            {info.data?.recent.map((event, index) => (
              <li key={event.at + ":" + index} className="flex gap-2">
                <span className="text-muted-foreground">{new Date(event.at * 1000).toLocaleTimeString()}</span>
                <span>{event.type}</span>
                <span>{[event.doc, event.obj].filter(Boolean).join(" / ")}</span>
                {event.props && <span className="text-muted-foreground">{event.props.join(", ")}</span>}
                {event.origin && <span className="ml-auto text-muted-foreground">{event.origin}</span>}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Hier beginnt die Arbeit der Gruppe</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="text-muted-foreground">Logik, Routen, Reaktion auf CAD-Änderungen:</span>{" "}
            <code>backend/app/projects/{id}/</code>
          </p>
          <p>
            <span className="text-muted-foreground">Oberfläche:</span> <code>frontend/src/features/{id}/</code>
          </p>
          <p>
            <span className="text-muted-foreground">Eigene API:</span> <code>/api/projects/{id}/*</code> ·{" "}
            <span className="text-muted-foreground">Live-Ereignisse:</span> <code>{id}.*</code>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
