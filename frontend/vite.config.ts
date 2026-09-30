/// <reference types="vitest/config" />
import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The browser knows ONLY the backend (port 8000). In dev mode Vite forwards
// /api and /ws there -- so the page stays same-origin, and the
// backend needs no CORS allowance (deliberately: see backend/app/security.py).
const BACKEND = "http://127.0.0.1:8000"

export default defineConfig({
  plugins: [
    // Must come BEFORE react(): generates src/routeTree.gen.ts from src/routes/.
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true, // fixed ports, no automatic search -- otherwise the proxy points into the void
    proxy: {
      "/api": { target: BACKEND },
      "/ws": { target: BACKEND, ws: true },
    },
  },
  build: {
    // The backend serves the built UI.
    outDir: "../backend/app/static",
    emptyOutDir: true,
    // Runs locally only, loaded from loopback -- bundle size is not an issue here.
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
})
