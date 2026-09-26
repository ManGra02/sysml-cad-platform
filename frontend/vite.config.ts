/// <reference types="vitest/config" />
import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Der Browser kennt NUR das Backend (Port 8000). Im Dev-Betrieb reicht Vite
// /api und /ws dorthin weiter -- die Seite bleibt damit same-origin, und das
// Backend braucht keine CORS-Freigabe (bewusst: siehe backend/app/security.py).
const BACKEND = "http://127.0.0.1:8000"

export default defineConfig({
  plugins: [
    // Muss VOR react() stehen: erzeugt src/routeTree.gen.ts aus src/routes/.
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
    strictPort: true, // feste Ports, keine automatische Suche -- sonst zeigt der Proxy ins Leere
    proxy: {
      "/api": { target: BACKEND },
      "/ws": { target: BACKEND, ws: true },
    },
  },
  build: {
    // Das Backend liefert die gebaute Oberflaeche aus.
    outDir: "../backend/app/static",
    emptyOutDir: true,
    // Laeuft nur lokal, von Loopback geladen -- Bundle-Groesse ist hier kein Thema.
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
})
