# SysML-CAD Platform

Gemeinsame Grundlage für zwei Projekte der Projektgruppe: **Bi-Directional
Synchronization** und **Missing CAD Component Recommendation**.

**Leitidee:** FreeCAD ist nur die *Brücke* zum CAD-Modell. Die Plattform — Oberfläche,
Projekt-Registry, jede Fachlogik — lebt in einem eigenen Python-Prozess, der von der
Browser-Anwendung gesteuert wird und FreeCAD lediglich als Dienst benutzt.

```
Browser (React + shadcn/ui)
   │  HTTP + WebSocket
   ▼
Plattform-Backend  :8000     eigener Prozess, eigene venv
   │  HTTP + WebSocket, Token im Authorization-Header
   ▼
FreeCAD-Brücke     :8765     Addon im FreeCAD-Prozess
```

---

## Läuft ausschließlich lokal

Alle drei Prozesse laufen auf dem Rechner des Nutzers, für genau einen Nutzer, und
binden nur an `127.0.0.1`. Das ist eine feste Annahme, keine vorläufige Vereinfachung.

**Ausdrückliche Nicht-Ziele:** kein HTTPS, keine Nutzerkonten, keine Rate-Limits, kein
Audit-Log, keine Verteidigung gegen bösartige Prozesse desselben Nutzers.

Was trotzdem abgesichert ist: jede Webseite im Browser des Nutzers kann Requests an
`localhost` schicken. Dagegen stehen Origin- und Host-Prüfung sowie ein Token, das
ausschließlich im `Authorization`-Header akzeptiert wird — auch beim WebSocket. Browser
können bei `new WebSocket()` keine Header setzen; damit ist der Brücken-WS für
Web-Angreifer strukturell unerreichbar.

---

## Einrichtung

Voraussetzungen: FreeCAD 1.1, git, [uv](https://docs.astral.sh/uv/), node ≥ 20, pnpm.

```bash
git clone <repo> && cd sysml-cad-platform

# Addon verlinken (Junction/Symlink, keine Kopie)
pwsh scripts/link-addon.ps1        # Windows
bash scripts/link-addon.sh         # macOS / Linux

# Diagnose -- sagt bei jedem Problem, was zu tun ist
"<FreeCAD>/bin/python.exe" scripts/doctor.py
```

Alternative zum Verlinken, gut zum Ausprobieren:

```bash
freecad -M "<repo>/bridge"
```

> **Das Repo gehört nicht in einen Cloud-Mirror** (Google Drive, OneDrive, Dropbox).
> `.git/objects`, `node_modules` und eine Addon-Junction darin erzeugen EPERM-Fehler,
> „datei (1)"-Duplikate und im schlimmsten Fall ein korruptes `.git`.

---

## Entwickeln

Drei Dinge laufen: FreeCAD, Backend, Vite.

```bash
# 1. FreeCAD starten, Workbench "SysML-CAD Brücke" wählen, Brücke starten
# 2. Backend
cd backend && uv sync && uv run python -m app --reload --dev
# oder alles auf einmal: scripts/dev.ps1 bzw. scripts/dev.sh
# 3. Frontend (einmalig: cd frontend && pnpm install)
cd frontend && pnpm dev            # -> http://127.0.0.1:5173
```

Im Dev-Betrieb öffnet man **http://127.0.0.1:5173**: Vite reicht `/api` und `/ws` an das
Backend weiter, das dafür mit `--dev` laufen muss (erlaubt den Origin `:5173`). Ohne Vite
liefert das Backend die gebaute Oberfläche selbst aus (`cd frontend && pnpm build`, dann
**http://127.0.0.1:8000**).

> **Windows: `pnpm` meldet „OpenSSL configuration error“?** Eine andere Installation
> (z. B. PostgreSQL) hat `OPENSSL_CONF` auf eine fehlende Datei gesetzt. Die Startskripte
> leeren die Variable für sich; von Hand: `$env:OPENSSL_CONF=""` vor `pnpm`.

### Im Browser bearbeiten

- Eingaben werden beim **Verlassen des Feldes oder mit Enter** übernommen, **Esc** verwirft.
  Jede Übernahme ist in FreeCAD genau **ein** Undo-Schritt („Browser: Box.Length“).
- Lage und Vektoren werden als Ganzes übernommen, wenn der Fokus die Gruppe verlässt.
- **Konflikte werden sichtbar, nie still überschrieben:** hat sich genau das bearbeitete
  Feld inzwischen in FreeCAD geändert, fragt ein Dialog, welcher Wert gelten soll.
  Änderungen an *anderen* Feldern desselben Objekts sind kein Konflikt. Technisch:
  `If-Match: <rev>` am PATCH, `409 rev_mismatch` mit dem aktuellen Stand.
- Gesperrte Felder tragen ein Schloss (schreibgeschützt) oder ƒ (an eine Expression
  gebunden – in FreeCAD bearbeiten).

**`PYTHONNOUSERSITE=1` gehört in jedes Startskript.** Das user-site-Verzeichnis wird mit
einem separat installierten Python geteilt und steht *vor* FreeCADs site-packages — ohne
das Flag schattet es die gebündelten Pakete. In FreeCADs Python wird nichts installiert.

### Tests

```bash
# Brücke -- braucht FreeCADs Python (aiohttp + unittest sind dort vorhanden, pytest nicht)
PYTHONNOUSERSITE=1 "<FreeCAD>/bin/python.exe" tests/bridge/run.py

# Backend -- ohne FreeCAD, gegen eine nachgebaute Bruecke
cd backend && uv run pytest

# Ende-zu-Ende: echte Bruecke, echtes Backend, simulierter Browser
cd backend && uv run python ../scripts/e2e/m5_acceptance.py

# Frontend -- reine Logik (Baum, Ereignisse, Drehung, Formate) und Typen
cd frontend && pnpm test && pnpm typecheck
```

Der Ende-zu-Ende-Test braucht die Ports 8000 und 8765 -- FreeCAD mit laufender Bruecke
vorher beenden. Er prueft den Abnahmefall aus M5: Bruecke stoppen, in FreeCAD Objekte
anlegen, Bruecke starten -- der Browser ist danach aktuell, ohne neu zu laden.

Läuft FreeCAD mit gestarteter Brücke, überspringen sich die Lebenszyklus-Tests von
selbst — sie brauchen Port 8765. Für den vollständigen Lauf die Brücke im Dock-Panel
stoppen.

`freecadcmd -t` wird **nie** automatisiert benutzt: es druckt `FAILED` und liefert
trotzdem Exit-Code 0. Eine CI darauf wäre dauerhaft grün.

---

## Aufbau

| Verzeichnis | Inhalt |
| --- | --- |
| `bridge/` | Das FreeCAD-Addon. Wird nach `Mod/` verlinkt. |
| `bridge/cad_contract/` | Gemeinsamer, abhängigkeitsfreier Vertrag — von beiden Pythons importiert. |
| `backend/` | Plattform-Backend (FastAPI), eigene venv. |
| `frontend/` | React + shadcn/ui, gebaut nach `backend/app/static/`. |
| `scripts/` | Verlinken, Diagnose, Entwicklungsstart. |
| `tests/` | `bridge/` (FreeCADs Python), `backend/` (gegen Mock), `contract/`. |

### Die eine Regel für `bridge/`

**Alles, was die FreeCAD-API nicht anfasst, gehört nicht in die Brücke.** Keine
Fachlogik, keine Registry, keine Auslieferung der Oberfläche, kein Proxy. Jede Änderung
dort kostet allen einen FreeCAD-Neustart, jede Änderung im Backend eine Sekunde.

Und: **jeder** Zugriff auf Dokument, Objekte oder Views läuft durch `dispatch()`. Die
FreeCAD-API ist nicht threadsicher. Der Dekorator `@main_thread_only` macht aus einem
sonst nicht-deterministischen Absturz in Coin3D einen klaren `RuntimeError` an der
Aufrufstelle.

`cad_contract` liegt bewusst *im* Addon-Verzeichnis: ein Geschwisterordner wäre durch die
Junction nicht erreichbar, weil FreeCAD nur `Mod/SysMLCadPlatform` sieht.

---

## Stand

| Meilenstein | Status |
| --- | --- |
| M0 Repo, Verlinkung, Addon lädt, `doctor` grün | ✅ |
| M1 Brücke: Server, Dispatch, `stop_bridge()` | ✅ |
| M2 Brücke: Lesen (Baum, Batch, Detail, Auswahl) | ✅ |
| M3 Brücke: Schreiben | ✅ |
| M4 Brücke: Events | ✅ |
| M5 Backend verbindet sich, Resync | ✅ |
| M6 Frontend: Explorer + Property-Editor, `If-Match` | ✅ |
| M7 Launcher + Projekt-Registry | offen |
| M8 Objekt-Lifecycle + Speichern | offen |
| M9 Produktions-Build | offen |

SysML v2 ist bewusst **nicht** Teil dieser Grundlage. Der Zugriff darauf ist reines HTTP
und gehört später ins Backend, ohne die Brücke zu berühren.
