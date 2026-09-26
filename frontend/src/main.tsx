import "./index.css"
import "@/lib/theme"

import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider, createRouter } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { handleFrame } from "@/features/cad/sync"
import { queryClient } from "@/lib/queryClient"
import { eventSocket } from "@/lib/ws"
import { routeTree } from "./routeTree.gen"

const router = createRouter({
  routeTree,
  // Route-Loader und WebSocket-Invalidierung teilen sich denselben Cache.
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
