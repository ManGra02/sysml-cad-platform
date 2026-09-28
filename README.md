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

Voraussetzungen: **FreeCAD 1.1**, git, [uv](https://docs.astral.sh/uv/), **Node 22 LTS**
(oder ≥ 20.19). pnpm ≥ 10 ist schön, aber nicht nötig: fehlt es oder ist es älter, nehmen die
Skripte `corepack pnpm` (kommt mit Node) in genau der Version aus `frontend/package.json`.

```bash
git clone <repo> && cd sysml-cad-platform
pwsh scripts/setup.ps1        # Windows
bash scripts/setup.sh         # macOS / Linux
```

`setup` erledigt alles in einem Lauf und ist wiederholbar (auch nach `git pull`):
Python-Umgebung (`uv sync`), Frontend-Abhängigkeiten, Oberfläche bauen, Addon nach FreeCAD
verlinken, Diagnose. Für eine zweite Arbeitskopie ohne Addon-Link: `-SkipLink` bzw.
`--skip-link`. Liegt FreeCAD nicht am üblichen Ort: `-FreeCadPython <pfad>` bzw.
`FREECAD_PYTHON=<pfad>`.

**Starten** — ein Prozess, eine Adresse:

```bash
pwsh scripts/start.ps1        # bzw. bash scripts/start.sh   -> http://127.0.0.1:8000
```

Das Backend liefert die gebaute Oberfläche selbst aus. Ist sie veraltet (nach `git pull`
oder eigenen Änderungen), baut `start` sie vorher neu. Dann FreeCAD starten, Workbench
„SysML-CAD Brücke“ wählen, Brücke starten — die Reihenfolge ist egal.

**Wenn etwas nicht geht:** `cd backend && uv run python ../scripts/doctor.py` (und für die
FreeCAD-Seite `"<FreeCAD>/bin/python.exe" scripts/doctor.py`). Jede Meldung nennt die Behebung —
auch „laufende Brücke hat einen anderen Vertrag → FreeCAD neu starten“ nach einem `git pull`.

Alternative zum Verlinken, gut zum Ausprobieren: `freecad -M "<repo>/bridge"`.

> **Das Repo gehört nicht in einen Cloud-Mirror** (Google Drive, OneDrive, Dropbox).
> `.git/objects`, `node_modules` und eine Addon-Junction darin erzeugen EPERM-Fehler,
> „datei (1)"-Duplikate und im schlimmsten Fall ein korruptes `.git`.

> **Windows: `pnpm` meldet „OpenSSL configuration error“?** Eine andere Installation
> (z. B. PostgreSQL) hat `OPENSSL_CONF` auf eine fehlende Datei gesetzt. Die Skripte
> leeren die Variable für sich; von Hand: `$env:OPENSSL_CONF=""` vor `pnpm`.

---

## Entwickeln

Mit Hot-Reload laufen drei Dinge: FreeCAD, Backend (`--reload --dev`), Vite.

```bash
pwsh scripts/dev.ps1          # bzw. bash scripts/dev.sh   -> http://127.0.0.1:5173
```

Im Dev-Betrieb öffnet man **http://127.0.0.1:5173**: Vite reicht `/api` und `/ws` an das
Backend weiter, das dafür mit `--dev` laufen muss (erlaubt den Origin `:5173`). Von Hand:
`cd backend && uv run python -m app --reload --dev` und `cd frontend && pnpm dev`.

| | `start` | `dev` |
| --- | --- | --- |
| Adresse | http://127.0.0.1:8000 | http://127.0.0.1:5173 |
| Prozesse | Backend | Backend + Vite |
| Oberfläche | gebaut, bei Bedarf neu | live, Hot-Reload |
| Backend-Code | Neustart nötig | lädt selbst neu |

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
# ... und ein Projektmodul, das programmatisch am CAD-Modell arbeitet
cd backend && uv run python ../scripts/e2e/m8_acceptance.py

# (Backend-Tests enthalten die Projekt-Registry: tests/backend/test_projects.py)

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

### Wo die eigene Logik hinkommt: Projektmodule

Jedes Projekt ist ein Python-Paket unter `backend/app/projects/<id>/` plus eine Oberfläche
unter `frontend/src/features/<id>/`. Die Startseite `/` wählt das aktive Projekt; die
Wahl gilt für alle Tabs und wird im Backend gemerkt (`~/.sysml-cad-platform/state.json`).

```python
class BdsModule(ProjectModule):
    id = "bds"

    def register_routes(self, router):          # -> /api/projects/bds/*
        @router.get("/mapping")
        async def mapping(): ...

    async def on_cad_event(self, event):         # jede Änderung aus FreeCAD (nur aktiv)
        if self.ctx.cad.is_own(event):            # Echo eigener Schreibvorgänge
            return
        obj = await self.ctx.cad.object(event["doc"], event["obj"])
        self.ctx.publish("mapping_changed", {...})   # -> Browser, WS-Typ "bds.mapping_changed"
```

- `self.ctx.cad` liest und schreibt das CAD-Modell über die Brücke. Fehler kommen als
  `CadError` (`code`, `status`, `detail`, bei Vorgängen `failed_op`).

**Mehrere Änderungen als ein Vorgang** — in FreeCAD genau ein Undo-Schritt, alles oder nichts:

```python
async with self.ctx.cad.transaction("Doc", "BDS: Motor anlegen") as tx:
    group = tx.create("App::DocumentObjectGroup", name="Antrieb")
    motor = tx.create("Part::Box", name="Motor", group=group, props={"Width": "12 mm"})
    tx.add_property(motor, "App::PropertyString", "SysMLId", value=element_id, group="SysML")
    tx.set_cells("Params", {"A1": "40 mm"}, aliases={"A1": "motor_laenge"})
    tx.set_expression(motor, "Length", "Params.motor_laenge")
name = tx.result.name(motor)   # echter Name -- FreeCAD benennt bei Kollision um ("Motor001")
```

| Operation | Zweck |
| --- | --- |
| `create(type, name, label=, group=, props=)` | Objekt anlegen (keine `*FeaturePython*`), optional in Gruppe/Part/Body |
| `delete(obj, force=False)` | löschen; hängen andere Objekte davon ab → `CadError("has_dependents")` |
| `patch(obj, props, if_match=)` | Properties setzen |
| `set_expression(obj, prop, expr)` | Formel binden (`None` entfernt sie) — die Bindung lebt in FreeCAD |
| `set_cells(sheet, cells, aliases)` | Tabellenzellen und Aliase (`None` leert) |
| `add_property` / `remove_property` | eigene Properties, z. B. die SysML-ID; werden in der `.FCStd` gespeichert |

Lesen: `documents()`, `tree(doc)`, `object(doc, name)`, `cells(doc, sheet, "A1:D100")`.
Jede Operation gibt es auch als Kurzform (`await cad.create(doc, ...)`), dann als eigener
Vorgang. Wird ein Objekt durch den Vorgang ungültig (etwa Formel auf einen unbekannten
Alias), wird alles zurückgenommen (`recompute_failed`); `transaction(..., strict=False)`
meldet es nur. Die Ereignisse eines Vorgangs erkennt `self.ctx.cad.is_own(event)`.
- Neue Projekte werden **ausdrücklich** in `backend/app/projects/registry.py` (`MODULES`)
  eingetragen und bekommen eine Route `frontend/src/routes/projects.<id>.tsx` plus einen
  Eintrag in `PROJECT_ROUTES` (`frontend/src/features/projects/queries.ts`).
- Namensraum: alles eines Moduls trägt seine id — Routen, WebSocket-Typen, Query-Keys, Ordner.
- `bridge/` wird dafür **nie** angefasst.

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
| M7 Launcher + Projekt-Registry | ✅ |
| M8 Programmatische CAD-Schnittstelle für Projektmodule | ✅ |
| M9 Produktions-Build, Einrichtung von Null | ✅ |

SysML v2 ist bewusst **nicht** Teil dieser Grundlage. Der Zugriff darauf ist reines HTTP
und gehört später ins Backend, ohne die Brücke zu berühren.
