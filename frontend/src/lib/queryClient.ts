import { QueryClient } from "@tanstack/react-query"

import { isFinal } from "@/lib/api"

// Frische kommt ueber den WebSocket: jede Aenderung in FreeCAD invalidiert
// gezielt. Das Fokus-Refetch bleibt als Netz fuer den Fall, dass man aus
// FreeCAD in den Browser zurueckwechselt, waehrend der Socket neu verbindet.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: (failureCount, error) => !isFinal(error) && failureCount < 2,
    },
    mutations: {
      // Nie automatisch wiederholen: der Nutzer soll einen Fehler sehen, und
      // ein Konflikt (409) ist eine Entscheidung, keine Stoerung.
      retry: false,
    },
  },
})
