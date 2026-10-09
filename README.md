# SysML-CAD Platform

Shared foundation for two projects of the project group: **Bi-Directional
Synchronization** and **CAD Reuse Assistant**.

**Guiding principle:** FreeCAD is only the *bridge* to the CAD model. The platform — UI,
project registry, all domain logic — lives in its own Python process, which is driven by
the browser application and uses FreeCAD merely as a service.

```
Browser (React + shadcn/ui)
   │  HTTP + WebSocket
   ▼
Platform backend   :8000     own process, own venv
   │  HTTP + WebSocket,                     │  HTTP (SysML v2 API)
   │  token in the Authorization header     ▼
   ▼                                    SysML v2 repository :8083   Flexo MMS, Docker (flexo/)
FreeCAD bridge     :8765     addon inside the FreeCAD process
```

---

## Runs locally only

All three processes run on the user's machine, for exactly one user, and bind only to
`127.0.0.1`. This is a fixed assumption, not a temporary simplification.

**Explicit non-goals:** no HTTPS, no user accounts, no rate limits, no audit log, no
defense against malicious processes running as the same user.

What is protected nonetheless: any web page in the user's browser can send requests to
`localhost`. This is countered by Origin and Host checks plus a token that is accepted
exclusively in the `Authorization` header — including for the WebSocket. Browsers
cannot set headers on `new WebSocket()`; this makes the bridge WS structurally
unreachable for web attackers.

---

## Setup

Prerequisites: **FreeCAD 1.1**, git, [uv](https://docs.astral.sh/uv/), **Node 22 LTS**
(or ≥ 20.19). pnpm ≥ 10 is nice but not required: if it is missing or older, the scripts
use `corepack pnpm` (ships with Node) in exactly the version from `frontend/package.json`.

```bash
git clone <repo> && cd sysml-cad-platform
pwsh scripts/setup.ps1        # Windows
bash scripts/setup.sh         # macOS / Linux
```

`setup` does everything in one run and is repeatable (also after `git pull`):
Python environment (`uv sync`), frontend dependencies, UI build, linking the addon into
FreeCAD, diagnostics. For a second working copy without the addon link: `-SkipLink` or
`--skip-link`. If FreeCAD is not in its usual location: `-FreeCadPython <path>` or
`FREECAD_PYTHON=<path>`.

**Starting** — one process, one address:

```bash
pwsh scripts/start.ps1        # or bash scripts/start.sh   -> http://127.0.0.1:8000
```

The backend serves the built UI itself. If it is stale (after `git pull` or your own
changes), `start` rebuilds it first. Then start FreeCAD, select the "SysML-CAD Bridge"
workbench, start the bridge — the order does not matter.

**If something doesn't work:** `cd backend && uv run python ../scripts/doctor.py` (and for the
FreeCAD side `"<FreeCAD>/bin/python.exe" scripts/doctor.py`). Every message names the fix —
including "running bridge has a different contract → restart FreeCAD" after a `git pull`.

Alternative to linking, good for trying things out: `freecad -M "<repo>/bridge"`.

> **The repo does not belong in a cloud mirror** (Google Drive, OneDrive, Dropbox).
> `.git/objects`, `node_modules` and an addon junction inside it cause EPERM errors,
> "file (1)" duplicates and, in the worst case, a corrupted `.git`.

> **Windows: `pnpm` reports "OpenSSL configuration error"?** Another installation
> (e.g. PostgreSQL) has set `OPENSSL_CONF` to a missing file. The scripts clear the
> variable for themselves; manually: `$env:OPENSSL_CONF=""` before `pnpm`.

---

## Development

With hot reload, three things run: FreeCAD, the backend (`--reload --dev`), Vite.

```bash
pwsh scripts/dev.ps1          # or bash scripts/dev.sh   -> http://127.0.0.1:5173
```

In dev mode you open **http://127.0.0.1:5173**: Vite forwards `/api` and `/ws` to the
backend, which must run with `--dev` for this (allows the `:5173` origin). Manually:
`cd backend && uv run python -m app --reload --dev` and `cd frontend && pnpm dev`.

| | `start` | `dev` |
| --- | --- | --- |
| Address | http://127.0.0.1:8000 | http://127.0.0.1:5173 |
| Processes | Backend | Backend + Vite |
| UI | built, rebuilt when needed | live, hot reload |
| Backend code | restart required | reloads itself |

### Editing in the browser

- Input is applied when you **leave the field or press Enter**; **Esc** discards it.
  Each applied edit is exactly **one** undo step in FreeCAD ("Browser: Box.Length").
- Placement and vectors are applied as a whole when focus leaves the group.
- **Conflicts are made visible, never silently overwritten:** if exactly the field being
  edited has changed in FreeCAD in the meantime, a dialog asks which value should win.
  Changes to *other* fields of the same object are not a conflict. Technically:
  `If-Match: <rev>` on the PATCH, `409 rev_mismatch` with the current state.
- Locked fields show a lock (read-only) or ƒ (bound to an expression
  – edit in FreeCAD).

### Languages

The UI is available in **English (default)** and **German**; switch at the top right
(the 文A icon), the browser remembers the choice. Implemented with `i18next` +
`react-i18next`:

- Texts live as JSON in `frontend/src/i18n/locales/en.json` (source of all keys)
  and `de.json` -- the format that translation tools (Crowdin, Weblate, i18n Ally) also
  read. They are part of the bundle and not loaded lazily: the UI works offline
  and starts without flicker.
- The typecheck checks every `t("…")` against `en.json` (typos get caught). That `de.json`
  is complete and has the same placeholders is checked by `src/i18n/i18n.test.ts`.
- New texts: add the key in **both** files; in components use
  `const { t } = useTranslation()`, outside React `i18n.t(…)` from `@/i18n`.
- Notation: `{{name}}` gets interpolated; `_one`/`_other` are plural forms (i18next
  chooses via `count`); `<strong>…</strong>` or similar inside a text is turned into real
  elements by the `<Trans>` component. `unitTypes` translates FreeCAD's quantity kinds
  (`Length` → "Länge" in German); unknown ones stay as they are.
- **Store errors as the cause, not as text.** Anything that keeps a message around (e.g. below
  an input field) stores the error itself (`ApiError`, `TranslatableError`) and
  calls `describeError()` only when displaying it -- otherwise the message stays in the old
  language after a language switch.
- **Errors are translated by their code, never by their message.** Bridge and backend
  respond in English and machine-readably (`error.code`, for `invalid_value` additionally
  `detail.reason`, for the bridge status `reason`); `describeError()` builds the text from that.
  Unknown codes show the English message.
- Property names and groups (`Length`, `Placement`, "Attachment") come from FreeCAD
  and stay untranslated – that is also what they are called in Python code and in FreeCAD's own editor.
- The FreeCAD side (workbench, commands, dock panel) follows the language FreeCAD
  actually displays (`FreeCADGui.getLocale()`, else the preference, else the system language):
  German or English. Texts in `bridge/bridge_addon/i18n.py`.

**`PYTHONNOUSERSITE=1` belongs in every start script.** The user-site directory is shared
with a separately installed Python and comes *before* FreeCAD's site-packages — without
the flag it shadows the bundled packages. Nothing gets installed into FreeCAD's Python.

### Tests

```bash
# Bridge -- needs FreeCAD's Python (aiohttp + unittest are available there, pytest is not)
PYTHONNOUSERSITE=1 "<FreeCAD>/bin/python.exe" tests/bridge/run.py

# Backend -- without FreeCAD, against a simulated bridge
cd backend && uv run pytest

# End-to-end: real bridge, real backend, simulated browser
cd backend && uv run python ../scripts/e2e/m5_acceptance.py
# ... and a project module that works on the CAD model programmatically
cd backend && uv run python ../scripts/e2e/m8_acceptance.py

# (Backend tests include the project registry: tests/backend/test_projects.py,
#  the SysML adapter against an in-memory Flexo: tests/backend/test_sysml.py,
#  and the AI adapter against a fake Ollama: tests/backend/test_ai.py)

# Frontend -- pure logic (tree, events, rotation, formats) and types
cd frontend && pnpm test && pnpm typecheck
```

The end-to-end test needs ports 8000 and 8765 -- quit FreeCAD with a running bridge
first. It checks the M5 acceptance case: stop the bridge, create objects in FreeCAD,
start the bridge -- afterwards the browser is up to date without reloading.

If FreeCAD is running with the bridge started, the lifecycle tests skip themselves
— they need port 8765. For the full run, stop the bridge in the dock panel.

`freecadcmd -t` is **never** used in automation: it prints `FAILED` and still
returns exit code 0. A CI based on it would be permanently green.

---

## Structure

| Directory | Contents |
| --- | --- |
| `bridge/` | The FreeCAD addon. Gets linked into `Mod/`. |
| `bridge/cad_contract/` | Shared, dependency-free contract — imported by both Pythons. |
| `backend/` | Platform backend (FastAPI), own venv. |
| `backend/app/sysml/` | SysML adapter: SysML v2 API client, parser, common engineering model, `/api/sysml/*`. |
| `backend/app/ai/` | AI adapter: Ollama Cloud, model per project, LangGraph agent and tools, `/api/ai/*`. |
| `flexo/` | Docker setup of the SysML v2 repository (Flexo MMS). |
| `data/examples/sysml/` | SysML v2 test models (e-bike demo, Flexo's own test model). |
| `frontend/` | React + shadcn/ui, built into `backend/app/static/`. |
| `scripts/` | Linking, diagnostics, dev startup. |
| `tests/` | `bridge/` (FreeCAD's Python), `backend/` (against a mock), `contract/`. |

### Where your own logic goes: project modules

Each project is a Python package under `backend/app/projects/<id>/` plus a UI
under `frontend/src/features/<id>/`. The start page `/` selects the active project; the
choice applies to all tabs and is remembered by the backend (`~/.sysml-cad-platform/state.json`).
"Close project" on the start page (`POST /api/projects/deactivate`) goes back to no active
project: the start page shows the pure selection, and no module receives FreeCAD events.

```python
class BdsModule(ProjectModule):
    id = "bds"

    def register_routes(self, router):          # -> /api/projects/bds/*
        @router.get("/mapping")
        async def mapping(): ...

    async def on_cad_event(self, event):         # every change from FreeCAD (active only)
        if self.ctx.cad.is_own(event):            # echo of our own writes
            return
        obj = await self.ctx.cad.object(event["doc"], event["obj"])
        self.ctx.publish("mapping_changed", {...})   # -> browser, WS type "bds.mapping_changed"
```

- `self.ctx.cad` reads and writes the CAD model via the bridge. Errors arrive as
  `CadError` (`code`, `status`, `detail`, for operations `failed_op`).

**Several changes as one operation** — exactly one undo step in FreeCAD, all or nothing:

```python
async with self.ctx.cad.transaction("Doc", "BDS: create motor") as tx:
    group = tx.create("App::DocumentObjectGroup", name="Drive")
    motor = tx.create("Part::Box", name="Motor", group=group, props={"Width": "12 mm"})
    tx.add_property(motor, "App::PropertyString", "SysMLId", value=element_id, group="SysML")
    tx.set_cells("Params", {"A1": "40 mm"}, aliases={"A1": "motor_length"})
    tx.set_expression(motor, "Length", "Params.motor_length")
name = tx.result.name(motor)   # actual name -- FreeCAD renames on collision ("Motor001")
```

| Operation | Purpose |
| --- | --- |
| `create(type, name, label=, group=, props=)` | create an object (no `*FeaturePython*`), optionally in a group/Part/Body |
| `delete(obj, force=False)` | delete; if other objects depend on it → `CadError("has_dependents")` |
| `patch(obj, props, if_match=)` | set properties |
| `set_expression(obj, prop, expr)` | bind a formula (`None` removes it) — the binding lives in FreeCAD |
| `set_cells(sheet, cells, aliases)` | spreadsheet cells and aliases (`None` clears) |
| `add_property` / `remove_property` | custom properties, e.g. the SysML ID; saved in the `.FCStd` |

Reading: `documents()`, `tree(doc)`, `object(doc, name)`, `cells(doc, sheet, "A1:D100")`.
Every operation also exists in short form (`await cad.create(doc, ...)`), then as its own
operation. If an object becomes invalid through the operation (e.g. a formula referencing an
unknown alias), everything is rolled back (`recompute_failed`); `transaction(..., strict=False)`
only reports it. The events of an operation are recognized by `self.ctx.cad.is_own(event)`.
**The SysML model** — `self.ctx.sysml` (the same for all modules):

```python
snap = await self.ctx.sysml.snapshot("EBike Demo")   # project name or id; head of the default branch
snap.version                                          # commit id -- record it with every result
for part in snap.leaf_parts():                        # physical parts, i.e. the ones that need CAD
    for attr in snap.attributes_of(part.id):          # value as modelled + in SI
        print(part.name, attr.name, attr.expression, attr.value_si, attr.unit_si)
snap.requirements()                                   # with extra["req_id"], extra["text"]
[r for r in snap.relations if r.kind == "satisfies"]  # requirement <- part

await self.ctx.sysml.write_attribute_value("EBike Demo", attr.id, 11200, unit="g")  # -> new commit (11.2 kg)
await self.ctx.sysml.diff("EBike Demo", old_commit, new_commit)                     # what changed
```

Errors arrive as `SysmlError` (`code`, `status`, `message`, `detail`) — e.g. `sysml_unreachable`
when Flexo isn't running, which is a normal state like a stopped bridge. The browser gets the
same data under `/api/sysml/*` (see `/api/docs`); people see it on the **SysML Model** page
(http://127.0.0.1:8000/sysml: part tree, values with SI units, requirements, commit history). Setup of the repository and test data:
[`flexo/README.md`](flexo/README.md); command line: `cd backend && uv run python -m app.sysml --help`.

**AI and agents** — `self.ctx.ai`, an LLM on **Ollama Cloud** with the project's own model
([LangChain](https://python.langchain.com/) / [LangGraph](https://langchain-ai.github.io/langgraph/)):

```python
from app.ai.agents import run
from app.ai.tools import cad_tools, sysml_tools

llm = self.ctx.ai.chat_model()                     # ChatOllama with this project's model
await llm.ainvoke("...")                           # also: llm.with_structured_output(Schema), llm.astream(...)

agent = self.ctx.ai.agent(sysml_tools(self.ctx) + cad_tools(self.ctx), prompt="You are ...")
result = await run(agent, "Which leaf parts of EBike Demo have no CAD object?")
result["answer"], result["steps"]                  # answer + which tools were called with what
```

Configuration lives in `backend/.env` (gitignored; copy `backend/.env.example`), a real
environment variable wins. The key never reaches the browser.

| Variable | Meaning |
| --- | --- |
| `OLLAMA_API_KEY` | key from https://ollama.com/settings/keys |
| `OLLAMA_MODEL` | default model for all projects |
| `OLLAMA_MODEL_BDS`, `OLLAMA_MODEL_CRA` | model per project (`OLLAMA_MODEL_<ID>`), overrides the default |
| `OLLAMA_BASE_URL`, `OLLAMA_TIMEOUT_S`, `OLLAMA_STATUS_TTL_S` | optional: endpoint, LLM timeout, status cache |

- `sysml_tools(ctx)` and `cad_tools(ctx)` are read-only; `cad_tools(ctx, write=True)` adds
  property writes and recompute. Own tools: any `async def` with type hints and a docstring,
  wrapped with `StructuredTool.from_function(coroutine=...)` or LangChain's `@tool`.
- `app/ai/agents.py` spells the tool loop out as a LangGraph `StateGraph` — the template for
  your own graphs (extra nodes, human approval before CAD writes, several agents).
- Each module has an example agent in `projects/<id>/agent.py`, callable as
  `POST /api/projects/<id>/agent {"message": "..."}` → `{model, answer, steps}`.
- Errors arrive as `AiError` (`ai_not_configured`, `ai_no_model`, `ai_unauthorized`,
  `ai_model_not_found`, ...). Without a key the platform runs as usual; the **AI** marker in
  the header shows green (ready), yellow (a project's model is not offered), red (not
  reachable / key rejected) or grey (no key), plus each project's model.

- New projects are registered **explicitly** in `backend/app/projects/registry.py` (`MODULES`)
  and get a route `frontend/src/routes/projects.<id>.tsx` plus an
  entry in `PROJECT_ROUTES` (`frontend/src/features/projects/queries.ts`).
- Namespace: everything belonging to a module carries its id — routes, WebSocket types, query keys, folders.
- `bridge/` is **never** touched for this.

### The one rule for `bridge/`

**Anything that doesn't touch the FreeCAD API does not belong in the bridge.** No
domain logic, no registry, no serving of the UI, no proxy. Every change
there costs everyone a FreeCAD restart; every change in the backend costs a second.

And: **every** access to the document, objects or views goes through `dispatch()`. The
FreeCAD API is not thread-safe. The `@main_thread_only` decorator turns what would
otherwise be a non-deterministic crash in Coin3D into a clear `RuntimeError` at the
call site.

`cad_contract` deliberately lives *inside* the addon directory: a sibling folder would not
be reachable through the junction, because FreeCAD only sees `Mod/SysMLCadPlatform`.

---

## Status

| Milestone | Status |
| --- | --- |
| M0 Repo, linking, addon loads, `doctor` green | ✅ |
| M1 Bridge: server, dispatch, `stop_bridge()` | ✅ |
| M2 Bridge: reading (tree, batch, detail, selection) | ✅ |
| M3 Bridge: writing | ✅ |
| M4 Bridge: events | ✅ |
| M5 Backend connects, resync | ✅ |
| M6 Frontend: explorer + property editor, `If-Match` | ✅ |
| M7 Launcher + project registry | ✅ |
| M8 Programmatic CAD interface for project modules | ✅ |
| M9 Production build, setup from scratch | ✅ |
| M10 SysML adapter: read/write the SysML v2 model via Flexo, `ctx.sysml`, `/api/sysml/*` | ✅ |
| M11 SysML Model page in the UI (read-only view of the model) | ✅ |

SysML v2 access lives in the backend (`backend/app/sysml/`), as plain HTTP to the SysML v2
API -- the bridge is not touched. The UI shows it read-only on the SysML Model page
(`frontend/src/features/sysml/`).
