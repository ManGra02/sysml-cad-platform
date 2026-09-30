import "./index.css"
import "@/lib/theme"
import "@/i18n" // before the first render: language is settled, no flicker

import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider, createRouter } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { handleFrame } from "@/features/cad/sync"
import { handleProjectFrame } from "@/features/projects/queries"
import { queryClient } from "@/lib/queryClient"
import { eventSocket } from "@/lib/ws"
import { routeTree } from "./routeTree.gen"

const router = createRouter({
  routeTree,
  // Route loaders and WebSocket invalidation share the same cache.
  context: { queryClient },
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0,
})

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

eventSocket.onFrame((frame) => handleFrame(queryClient, frame))
eventSocket.onFrame((frame) => handleProjectFrame(queryClient, frame))
eventSocket.start()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
