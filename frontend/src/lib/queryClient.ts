import { QueryClient } from "@tanstack/react-query"

import { isFinal } from "@/lib/api"

// Freshness comes via the WebSocket: every change in FreeCAD invalidates
// selectively. The focus refetch remains as a safety net for when you switch
// back from FreeCAD to the browser while the socket is reconnecting.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: (failureCount, error) => !isFinal(error) && failureCount < 2,
    },
    mutations: {
      // Never retry automatically: the user should see an error, and
      // a conflict (409) is a decision, not a malfunction.
      retry: false,
    },
  },
})
