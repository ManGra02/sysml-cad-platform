# CLAUDE.md — SysML v2 ↔ CAD verification PoC

## Goal
Check SysML v2 requirements automatically against CAD geometry. CI turns red when
the CAD model violates a system requirement. Later: a mapping store, AI-assisted
mapping proposals, bidirectional sync, SMT-based verification.

**Status: stages A, A2, E and H complete; 280 tests pass** (266 plus 14
skipped without the optional AI SDKs, which is how CI's first step runs). The verification
chain runs end to end (SysML v2 API → extractor → CAD adapter → verdict → exit
code), and on top of it the mapping can now be *proposed*: a catalogue of both
sides, four gates over any proposed entry, a proposal store, a human
confirmation step that writes into `mapping.yaml`, a stdlib baseline proposer
and a Claude one. The server side runs on the `hni-ase/SysML-v2-API-Services`
fork. All three reference runs at the bottom of this file reproduce exactly,
digests included.

Four models are published and captured, **each as its own project** under
`projects/<name>/` — `motor_housing` (one part), `gearbox` (three parts, ten
attributes, an interface dimension and an assembly mass budget), and `box1` and
`box2` (one cuboid each, checked against `projects/box<n>/Box<n>.step`,
exported from the browser CAD Chili3D -- the first CAD files this repository did
not generate, and the reason the axis convention is now configuration). A project is
one SysML model plus the mapping that ties it to CAD (FREQ-3: "the mapping is
stored with the project"); every command works on exactly one, chosen with
`PROJECT=<name>`, and no run ever merges two. The baseline proposer scores
**2/2 and 11/11 with zero false positives** against each project's own gold set.

The AI path has now been run for real, against the University of Paderborn
gateway (`https://ai-gateway.uni-paderborn.de/v1/`, OpenAI protocol, 74 models).
Three models measured — against the **former merged gold set** (13 attributes
across both models, before projects existed; the baseline row is from the same
run). Not directly comparable to today's per-project 2/2 and 11/11, and part of
every model's difficulty was the merged excerpt itself: two `Housing`s from two
models with nothing to tell them apart. Re-measuring per project is the obvious
next run.

| proposer | hit@1 | wrong@1 | missed | gateway |
|---|---|---|---|---|
| `baseline:difflib` (then) | **11/13** | 2 | 0 | — |
| `gwdg.gemma-4-31b-it` | 4/13 | 1 | 8 | UPB |
| `gwdg.qwen3.5-397b-a17b` | 3/13 | **5** | 5 | UPB |
| `gemini-3.8-flash` | 4/13 | **0** | 9 | AI Studio |

Two gateways, one backend, no code difference: Google AI Studio speaks the same
protocol at `https://generativelanguage.googleapis.com/v1beta/openai/` and
accepts the project's real proposal schema unchanged.

**Three models, three different failure modes, and the interesting axis is not
hit rate.** Gemini 3.8 Flash returned exactly two candidates for thirteen
attributes -- and both were right, with nothing invented and nothing dropped.
Perfect precision, poor recall: it takes the prompt's "a gap a human fills is
cheaper than a wrong mapping a human has to detect" literally, where
qwen3.5-397b ignored it entirely. By `wrong@1`, the column that actually costs
review time, Gemini is the best model tested and the largest one is the worst.
Whether the prompt is now *too* conservative is an open question and a
prompt-tuning experiment, not a code change.

**Model size predicted nothing.** The largest model scored worst and in the
dangerous direction -- five confident wrong answers against Gemma's one and
Gemini's none. Its systematic error is the same
one the difflib baseline made before identity scoring was added: it proposes the
`gearbox` module (the whole assembly) for `housing.length`, `housing.width` and
`housing.height`. The assembly's X extent happens to equal the housing's, so
three of those would have produced *plausible numbers from the wrong object*.

In a live `make propose` run, Gemma's five candidates were **all rejected by the
gates**, four for proposing a *volume* where the model asks for a length.
Nothing reached the proposal store. That is the ordering constraint paying off
in production rather than in a test: a weak model here is useless, not
dangerous -- and "bigger model" is not a synonym for "better proposer", which
is precisely why the scoreboard was built before the AI was.

Stage A re-anchored the mapping on *parts* (resolved through the model's own
`satisfy` link), put a `CadAdapter` seam under the CAD side, made verdicts
three-valued, and made every run record the model states it came from. Stage A2
put a STEP adapter under the same seam, so a file exported by any CAD system is
measurable — with no new dependency, because build123d already brings OCCT.

Stage E added the gates (dimension, existence, uniqueness, plausibility) and the
confirmation step, which is what makes FREQ-5 structural rather than a matter of
discipline. Stage H added proposers behind one interface, scored against a gold
set. The ordering was the point: **gates before AI**, so an AI suggestion is
machine-checked before it ever reaches a human's attention, and human-confirmed
before it can reach a verdict.

## Architecture

Four containers, one Compose project (`sysml-cad-poc`), one network:

| Container | Role | Port |
|---|---|---|
| `dev` | Devcontainer, Python 3.14, virtualenv at `/opt/venv` | — |
| `sysml2-postgres` | PostgreSQL 16, database `sysml2` | 5432 |
| `sysml2-api` | SysML v2 API Services (Play/Scala/Hibernate) | 9000 |
| `sysml2-jupyter` | SysML v2 kernel, `%publish` into the repository | 8888 |

Compose files: `docker/docker-compose.yml` + `.devcontainer/docker-compose.dev.yml`
(an overlay that adds `dev`). The two are always loaded together.

**Networking rule:** between containers, address services by service name
(`sysml-api:9000`, `postgres:5432`). `localhost` works only from the host.
`src/sysmlcad/config.py` reads `SYSML_API_URL`; the overlay sets it to
`http://sysml-api:9000`.

## Commands — and where to run them

**Inside the devcontainer:**
```bash
# Every command below works on ONE project: `PROJECT=<name>`, default
# motor_housing. `make projects` lists them. There is no "newest" fallback.
make projects                   # what projects exist under projects/
make publish NB=notebooks/04_publish_box2.ipynb   # %publish without clicking
make capture PROJECT=box2       # server state -> projects/box2/elements.json
make cad                        # CAD scripts, writes out/motor_housing.step
make verify                     # verify the default project from its capture
make verify PROJECT=gearbox     # ...another project
make verify-api                 # verify against the live server, matched BY NAME
make gates                      # is the MAPPING sound? (not: is the design ok)
make catalog                    # what exists on each side, as data
make explore-cad FILE=x.step    # what is inside a STEP file: node names, sizes
make step-fixtures              # regenerate fixtures/step/ (they are committed)
python -m sysmlcad.verify -p gearbox api   # same as make verify-api PROJECT=gearbox
make test                       # pytest, JUnit XML to out/ (280 tests)

# Mapping proposals -- nothing here can change a verdict
make propose                    # baseline proposer -> projects/<name>/proposals.yaml
make propose AI=claude          # ask Claude instead (needs the SDK + a key)
make propose AI=openai          # ...or any OpenAI-protocol server, local too
make proposals                  # what is waiting for a decision
make confirm ID=p-01            # gate it again, then write it into mapping.yaml
make propose-score              # hit rate against projects/<name>/gold_mapping.yaml
python -m sysmlcad.explore -p motor_housing   # element dump to out/elements.json
python -m sysmlcad.explore -p motor_housing MaxLength   # tree of one requirement
python -m sysmlcad.explore_cad fixtures/step/gearbox.step   # the CAD side
```

**On the host (needs Docker access):**
```bash
make secret     # PLAY_SECRET into docker/.env, if it is not there yet
make vendor     # clone the hni-ase fork into vendor/ and patch hbm2ddl.auto
make api        # build/start sysml-api (runs secret + vendor first)
make jupyter    # Jupyter container, http://localhost:8888/?token=sysmlcad
make logs
make down
make up         # CAUTION: starts EVERYTHING including dev and jupyter. Not
                # needed in the devcontainer workflow -- `make api` is enough.
```
NEVER run `make venv` in the devcontainer — the virtualenv already exists in the
image at `/opt/venv`.

Opening the devcontainer no longer needs `make secret` first: `initializeCommand`
in `devcontainer.json` runs on the host before Compose and writes a fresh
`PLAY_SECRET` into `docker/.env` when the file is missing.

## File tree

```
.devcontainer/     devcontainer.json, docker-compose.dev.yml, Dockerfile
docker/            docker-compose.yml, jupyter.Dockerfile, .env (gitignored),
                   .env.example
                   (no api-services.Dockerfile any more -- the fork ships one)
vendor/            hni-ase/SysML-v2-API-Services (git clone, not in the repo)
.github/workflows/ verify.yml -- CI runs against the CAPTURES, not the API
                   (deliberate: CI must be able to go green without a server).
                   Step 1: requirements.txt only, AI tests skip. Step 2: the
                   AI SDKs installed, AI tests run -- still no key
models/            motor_housing.sysml, gearbox.sysml, box1.sysml, box2.sysml
notebooks/         01_publish_motor_housing.ipynb, 02_publish_gearbox.ipynb,
                   03_publish_box1.ipynb, 04_publish_box2.ipynb
cad/               motor_housing.py, gearbox.py (two-part assembly),
                   export_fixtures.py (writes fixtures/step/)
projects/          ONE DIRECTORY PER SYSML MODEL. Everything that belongs to a
                   model lives together, and nothing is shared between two.
  <name>/
    project.yaml   name + sysml_project (the Package / server project name),
                   optionally `axes:` -- which bbox axis a named dimension
                   lies along on this project's CAD side
    *.step         the project's own CAD exports, if any (box1, box2)
    mapping.yaml   schema v2: parts ↔ CAD objects, attributes ↔ measurements
    elements.json  captured API response -- the offline source for
                   requirements, catalogue and tests. Checked on load: its
                   Package must be `sysml_project`, or it is refused
    gold_mapping.yaml   the answer key for scoring proposers on this model
    proposals.yaml machine-written; committed, because a rejection is worth
                   remembering. No verification run opens it
fixtures/          ai_response.json   (a CONSTRUCTED model response, so the AI
                                       proposer's validation is testable with
                                       no key; says so in its own _comment)
                   step/*.step        (committed STEP fixtures, shared)
src/sysmlcad/      config, units, model, sysml_client, extract, mapping,
                   verify, explore
                   project.py     Project: one model, one mapping, no guessing;
                                  DEFAULT_AXES + the project's `axes:`
                   publish.py     runs a publish notebook on the Jupyter kernel
                   catalog.py     what exists on each side, as data
                   gates.py       is the mapping sound (≠ is the design ok)
                   proposals.py   the proposal store
                   propose.py     Proposer protocol, difflib baseline,
                                  AI_PROPOSERS registry + build_proposer()
                   propose_ai.py  LlmProposer base (prompt, schema, excerpt,
                                  verification) + the Claude backend
                   propose_openai.py  any OpenAI-protocol server
                   confirm.py     human confirmation -> mapping.yaml
                   score.py       hit rate against the gold set
src/sysmlcad/adapters/   __init__.py (CadAdapter protocol, CadTarget),
                         build123d_adapter.py, step_adapter.py,
                         measurements.py (vocabulary over a Shape)
src/sysmlcad/explore_cad.py   what is inside a STEP file
tests/             test_extract.py, test_requirements.py, test_verify.py,
                   test_project.py, test_build123d_adapter.py,
                   test_step_adapter.py, test_catalog.py, test_gates.py,
                   test_confirm.py, test_propose.py, test_propose_ai.py,
                   test_propose_openai.py, test_sysml_client.py
pyproject.toml     package metadata + pytest config (pytest.ini is gone)
out/               STEP, JUnit XML, dumps. Only *.step and *.xml are
                   gitignored; out/relevant.txt (a real API payload excerpt)
                   and out/llm_request.txt (a recorded proposer request, made
                   before the prompt stopped mentioning densities) are
                   committed as reference material
```

## Data flow

1. `extract.load_with_context(project, "api")` → `fetch_elements()` →
   `SysMLClient.project_named()` + `all_elements()` (paginated) →
   `extract()`, which first runs `resolve_satisfies()` to learn which
   PartUsages each requirement is about → one
   `Requirement(id, subject, operator, limit: pint.Quantity)` per satisfying
   part, the definitions it could not read (with the reason), and the
   project and commit ids
2. `mapping.load_mapping()` → `parts:` (SysML part ↔ adapter + CAD object) and
   `attributes:` (SysML attribute ↔ measurement method, unit, direction,
   tolerance, status)
3. `verify.AdapterPool` instantiates the adapter named by the part entry;
   `adapter.measure(obj, method, args)` returns a pint quantity
4. `Requirement.evaluate()` compares with a dimension check →
   `(status, deviation)` → `Verdict`
5. `verify.run()` → `Run(context, verdicts, gaps)`; `report()` → table, exit 0/1

An unevaluable requirement becomes a **gap**, not a pass: a definition the
extractor could not read, no confirmed mapping, an `Unsupported` from the
adapter (including malformed `args:`), or a `DimensionMismatch` /
`BadTolerance` (mapping faults, reported as a gap here and diagnosed by
`make gates` — letting them escape would take every other verdict in the run
down with it). Gaps are reported and do not fail the run. FREQ-2: report the
gap, never substitute a value.

**How a mapping entry comes to exist** — the second flow, which cannot touch the
first:

1. `catalog.load_catalog()` → `Catalog(parts, targets)`: SysML part usages with
   their attributes and *value types*, CAD objects with the measurements they
   actually support. One excerpt, three consumers (gates, proposers, explorers)
2. a `Proposer` (`DifflibProposer`, `ClaudeProposer`) turns that into
   `Proposal`s with a confidence and a rationale (FREQ-4)
3. `propose.gate()` runs every candidate through `gates.check_proposal()`
   **before storing it** — measured on the object the candidate names, and
   refused if its part is already mapped to a different one; the rejects are
   reported, not silently dropped
4. survivors go to `projects/<name>/proposals.yaml` with `status: proposed`.
   No verification run opens that file
5. `confirm.py` re-gates one, then appends it to `mapping.yaml` with the
   confirming user and date (FREQ-5). Only now can a run use it

## Solved pitfalls — DO NOT undo these

**SysML v2 API Services**
- There is no official image. The `hni-ase` fork ships its own Dockerfile
  (`eclipse-temurin:11-jdk-jammy` plus sbt 1.2.8), which is why this repo has no
  `docker/api-services.Dockerfile` any more. `make vendor` clones the fork into
  `vendor/`; Compose builds from there.
- The JDBC connection now comes from the fork's environment variables —
  `SYSML_JDBC_URL`, `SYSML_JDBC_USER`, `SYSML_JDBC_PASSWORD`, set in
  `docker/docker-compose.yml`. The hardcoded `localhost:5432` in
  `conf/META-INF/persistence.xml` only applies when they are unset, so the old
  `sed` patch for the URL is gone.
- `hbm2ddl.auto` is the one setting the fork does **not** expose. `make vendor`
  patches it from `create-drop` to `update` with `sed` immediately after
  cloning — otherwise the whole schema is dropped on every clean stop. Re-run
  `make vendor` after deleting and re-cloning `vendor/`.
- `sbt run` (dev mode) dies on EOF on stdin, even with `stdin_open`/`tty`. The
  fork's Dockerfile therefore runs `sbt stage` at build time and symlinks the
  launcher to `/app/start-sysml` — its `find` filters out the `.bat` sibling,
  which is the same trap we used to spell our way around.
- Play's `AllowedHostsFilter` rejects `Host: sysml-api:9000` with a 400, and the
  fork's own CMD does not account for it. Compose overrides the command with
  `/app/start-sysml -Dhttp.address=0.0.0.0 -Dhttp.port=9000
  -Dpidfile.path=/dev/null -Dplay.filters.hosts.allowed.0=.
  -Dplay.http.secret.key=${PLAY_SECRET}`.
- **`-Dpidfile.path=/dev/null` is load-bearing.** Play writes `RUNNING_PID`
  into the container's filesystem; after an unclean stop (a closed VS Code
  window with `shutdownAction: stopCompose`, a host shutdown) the file
  survives, and restarting the SAME container dies at once with "This
  application is already running (Or delete .../RUNNING_PID)", exit 255.
  `make logs` hides it: it replays the old run's Hibernate output first, so
  the container looks busy while it is down -- `docker ps -a` and
  `docker logs --tail 30 sysml2-api` tell the truth. A container stuck in that
  state is fixed by recreating it (`docker rm sysml2-api && make api`); the
  database lives in the `pgdata` volume and survives.
- The first start takes minutes (schema creation, ~8200 tables), and every
  start after that still takes about 2-3 minutes: with `hbm2ddl.auto=update`
  Hibernate compares the whole schema before Play opens port 9000. It is ready once
  `Listening for HTTP` appears in the log and `curl localhost:9000/projects`
  returns 200.

**Devcontainer**
- Base image `mcr.microsoft.com/devcontainers/python:3.14-trixie`.
- OCP links hard against `libGL.so.1`, `libGLX`, `libX11` — even headless.
  apt: `libgl1 libx11-6 libxau6 libxdmcp6 libxext6 libxrender1`.
  No Mesa needed; this is only about symbol resolution.
- The virtualenv lives at `/opt/venv`, outside the bind mount (cadquery-ocp is large).
- `ENV PATH` is not enough: VS Code probes through a login shell, and the default
  shell is **zsh**. PATH is therefore also set in `/etc/profile.d/10-venv.sh`,
  `.bashrc`, `.zshrc`, and in `remoteEnv` in devcontainer.json.
- `forwardPorts` was **removed** — otherwise VS Code occupies host port 9000 and
  `sysml2-api` cannot bind.
- The Compose env file lives at `docker/.env`, **not** in the project root.
  Compose resolves it against the directory of the FIRST `-f` file, and the Dev
  Containers extension builds its own compose command with no way to pass
  `--env-file`. Anywhere else, opening the devcontainer dies at
  `docker compose config` with `required variable PLAY_SECRET is missing a value`
  — even though `runServices` is only `dev` + `postgres`, because `config`
  interpolates the whole merged file, `sysml-api` included.
- That failure is now prevented on a fresh clone: `initializeCommand` in
  `devcontainer.json` runs **on the host, before Compose**, and writes a random
  `PLAY_SECRET` into `docker/.env` if the file does not exist. `make secret`
  does the same thing by hand.
- Python 3.14: `ezdxf` has no cp314 wheels and runs pure-Python. That affects DXF
  only, not STEP. `lib3mf` DeprecationWarnings are expected and harmless.
- **build123d 0.11:** `export_step(part, path)` is a MODULE FUNCTION, not a method
  on the part. Older examples on the web show `part.export_step(...)`.
- Measurements: `part.volume` (mm³), `part.bounding_box().size.X`,
  `part.center(CenterOf.MASS)`, `len(part.faces())`. These now live in
  `adapters/build123d_adapter.py`; `measure.py` is gone.
- The adapter reads `MATERIAL` and `DENSITY_G_PER_CM3` from the CAD module, so
  density is no longer duplicated in `mapping.yaml`. An `args` override remains,
  for replacement-part studies ("what if this were plastic?").
- `Build123dAdapter.state_id()` hashes the source of the loaded CAD modules. For
  code-CAD the script *is* the design state, so that digest is exact, not an
  approximation.

**STEP files / the step adapter**
- **The axis convention is configuration, not code.** CAD systems disagree on
  which axis a "length" lies along: Chili3D writes a box's Length along Y,
  Width along Z, Height along X (measured on Box1 300/400/500 -> X 500, Y 300,
  Z 400 and Box2 100/200/300 -> X 300, Y 100, Z 200); build123d and FreeCAD
  use X, Y, Z. `project.DEFAULT_AXES` is the default, and `axes:` in
  project.yaml overrides it per project (validated: X/Y/Z only, and length,
  width, height on three different axes). It flows through `Catalog.axes` to
  the baseline proposer (it used to be the hard-coded `_AXIS_BY_NAME`), into
  the LLM excerpt (an `axes for bbox_size:` line) and into the gates:
  `gates.off_axis()` marks an entry measured along another axis as
  plausibility `unknown`, never `invalid` -- a part may lie on its side. A run
  does NOT read `axes:`; it measures what each confirmed entry states, so the
  mapping digest still covers everything that decides a verdict. With X, Y, Z,
  box1 reported MaxLength VIOLATED (500 > 300) -- correct under that
  convention, and why it became configurable. Never pick an axis because its
  extent matches the requirement's number: that passes every check by
  construction.
- Chili3D's STEP product name is the generic "Open CASCADE STEP translator
  8.0 <n>", so a single-root export is addressed without `#node`. No material
  in the file, so the box models ask for no mass.
- A project's own STEP files live in `projects/<name>/`; `load_catalog()` adds
  that directory to the shared `fixtures/step/`, so the proposer sees them. The
  baseline scores 3/3 on box1 and box2 from an empty mapping.
- **Publishing without clicking:** `make publish NB=notebooks/<nb>.ipynb` runs
  a notebook's code cells on the SysML kernel of the Jupyter container
  (`make jupyter` first) over Jupyter's REST + websocket API (token
  `sysmlcad`, `websockets` needed); `make capture PROJECT=<name>` then stores
  the server state as the offline capture. **The SysML kernel reports a parse
  error as printed `ERROR:` text and still answers `status: ok`** --
  `publish.py` treats such a line as failure and stops, or the `%publish` cell
  would run on a model that did not parse. It also warns when the kernel's
  `API base path` is not `SYSML_API_URL`.
- `Shape.cast()` on the BASE class is an `@abstractmethod` and returns `None`.
  `Shape.shape_LUT` maps to class *names* (strings), not classes. The adapter
  therefore keeps its own explicit `TopAbs_* -> build123d class` table.
- A file with several ROOT shapes has no "whole file". `_node` refuses the
  bare path, so `catalog()` lists each root as `file#name` -- it used to list
  them under the bare path and raise on the first multi-root export it met.
- Malformed `args:` (a typo, `axis: Q`, `density_g_per_cm3: 0`) raise
  `Unsupported`, never TypeError/AttributeError: `adapters.check_args()`
  binds the signature before the call and `check_density()` insists on a
  positive number. One typo in mapping.yaml used to lose the whole run.
- `build123d.import_step()` MANGLES node names: it translates `" .()"` to `"_"`,
  so `Housing (rev A)` becomes `Housing__rev_A_`. Since stable identity through
  names is the core convention, the adapter drives XCAF
  (`STEPCAFControl_Reader`) directly instead. `import_step` also surfaces
  colours but no materials.
- `xstep.cascade.unit` is a PROCESS-GLOBAL OCCT static. It reads empty before
  the first reader is constructed and `MM` afterwards. The adapter sets it on
  every read rather than trusting whatever ran before -- a silent factor of
  25.4 would produce confident, wrong verdicts.
- `export_step(..., unit=Unit.IN)` only DECLARES the unit, it does not rescale
  the geometry. A genuine inch fixture has to be scaled first
  (`build().scale(1 / 25.4)`), otherwise you are testing a mislabelled mm part.
- `XCAFDoc_MaterialTool.GetMaterial` does not exist in OCP; there is
  `GetMaterial_s` with out-parameters that do not bind back in Python. Use
  `GetDensityForShape_s(label)`, which returns `0.0` when no material is
  assigned.
- build123d does not export `CompSolid` at the top level -- import `Compound`,
  `Solid`, `Shell` and map COMPSOLID onto `Compound`.
- `export_step` writes names and assembly structure (`STEPCAFControl_Writer`,
  `SetNameMode(True)`), which is why the repo can generate its own assembly
  fixtures instead of committing a foreign binary it cannot regenerate.

**Jupyter / SysML kernel**
- conda-forge `jupyter-sysml-kernel=0.60.1`, `openjdk>=21`.
- The JupyterLab extension is deliberately NOT installed: it uses the old
  `labextension install` path, which fails under Lab 4, and only adds syntax
  highlighting.
- The standard library from `SysML-v2-Release` is cloned to `/opt/sysml.library`
  and `ISYSML_LIBRARY_PATH` points at it. Without it, every `import ISQ::*` fails.
- **Critical:** the kernel does NOT read `ISYSML_API_BASE_PATH` from the process
  environment; it reads it from the `env` block of its `kernel.json`
  (`/opt/conda/share/jupyter/kernels/sysml/kernel.json`). Without the patch,
  `%publish` publishes to the public server `sysml2.intercax.com`. The Dockerfile
  patches kernel.json.

**SysML v2 syntax (release 0.60.1)**
- Visibility on imports is mandatory: `private import ISQ::*;`, not `import`.
- `satisfy` needs a requirement **usage**, not a definition:
  ```
  requirement maxLengthCheck : MaxLength;
  satisfy maxLengthCheck by motorHousing;
  ```
- Units are not fields: `120 [mm]` becomes an `OperatorExpression` with
  `operator: "["`, operand 0 a `LiteralInteger`, and operand 1 a library
  `AttributeUsage` with `declaredShortName: "mm"`.

**The satisfy link, and dotted paths**
- `satisfy c by gearbox.housing` does NOT serialise like `satisfy c by gearbox`.
  A plain reference is a `Membership` pointing straight at the PartUsage; a
  dotted path becomes an anonymous `Feature` owning one `FeatureChaining` per
  segment, in order, and **the last link is the subject**:

  ```
  FeatureReferenceExpression
    -> OwningMembership.memberElement -> Feature
         |- FeatureChaining.chainingFeature -> PartUsage[gearbox]   first
         `- FeatureChaining.chainingFeature -> PartUsage[housing]   LAST = meant
  ```

  Nearest-match search finds `gearbox` and is wrong in the worst available way:
  it measures the assembly for a requirement about one component and reports a
  confident verdict. This actually happened -- the first `verify api` against the
  published gearbox resolved all four requirements to `gearbox`. See
  `extract._chained_subject` and `test_a_dotted_satisfy_resolves_to_the_last_link`.
- Order comes from the order of `ownedRelationship`; there is no index field on
  `FeatureChaining`. If the last link does not resolve to a usage, the resolver
  returns nothing and the caller falls back rather than picking another link.
- A part's package is found by walking `owner` **upward**, which is the one
  place that is right: `owner` is in `_UPWARD_FIELDS` and never followed during
  a downward search. A nested part needs several steps to reach its package.

**API details**
- Finding the server project BY NAME lives in one place,
  `SysMLClient.project_named()`; `verify api`, `catalog api` and `explore`
  used to carry three copies of it.
- `head_commit()` reads the project's `defaultBranch` and returns that
  branch's `head`. It used to take `commits[0]` of `/projects/{id}/commits`,
  which assumes newest-first order. Checked against the live server on
  2026-09-26: each project has one commit, so both routes agreed -- but only
  the branch says which commit is current. The commit list is a fallback for
  exactly one commit; several without a branch head is an error, not a pick.
  `tests/test_sysml_client.py` pins this against an `httpx.MockTransport`.
- **The motor_housing capture predates the server's current publish.** Same
  164 elements with the same content, but different element ids: the capture
  was taken on 2026-09-03 19:03, the server project republished at 23:15.
  Verdicts are identical; the element id an offline VIOLATED line cites
  (`72f3b6a1…`) does not exist on the server. The gearbox capture matches the
  server id for id.
- `/projects/{id}/commits/{cid}/elements` paginates — 100 per page by default,
  and the client asks for `page[size]=200`. The next page is in the Link header.
  `SysMLClient.all_elements()` follows it; `elements()` returns the first page
  only and exists for probing.
- `explore.py` has a `depth > 8` limit in `walk()`, which truncates the path to
  the unit. Raise it when debugging.

**Mapping proposals, gates and the AI**
- **A proposal is gated on the object it names.** `merged_mapping()` used to
  keep the EXISTING part entry, so a candidate for an already-mapped part was
  measured on the part's current object: `cover.mass -> gearbox#Housing`
  passed every gate with the cover's own mass, and confirming it appended an
  attribute entry that the run then measured on `gearbox#Cover`. The reviewer
  approved one object; the mapping recorded another. Now the merged view
  carries the proposal's own part entry, and `gates.check_proposal()` marks a
  different object for an already-mapped part as `invalid` under uniqueness
  (`code=PART_CONFLICT`, summarised once per part in `make propose`). A wrong
  part mapping is an edit to `parts:`, in review. Guarded by
  `test_a_proposal_naming_another_object_for_a_mapped_part_is_refused`.
- **`reject` refuses a proposal that is no longer pending.** Rejecting a
  confirmed one left proposals.yaml saying "no" while mapping.yaml carried the
  entry. Undoing a confirmation is setting the entry to `disabled`.
- **The confirm safety net uses explicit checks, not `assert`.** `python -O`
  strips asserts. It also checks that the part reads back as the proposed one.
- **A YAML round-tripper is not a safe way to edit `mapping.yaml`.** Measured,
  not assumed: `ruamel.yaml` 0.19.1 preserves the comments but still rewrites 38
  lines of today's file — list indentation (`  - ` becomes `- `), `tolerance:
  null` becomes an empty value, and a wrapped double-quoted note is re-wrapped
  somewhere else. `confirm.py` therefore renders the new entry as text and
  inserts it at the end of its section, leaving every existing byte alone, then
  re-parses the result and restores the original if it does not read back as
  intended. The dependency was tried and dropped; do not reintroduce it.
- **One project, one capture, never merged.** The catalogue used to glob every
  `fixtures/*elements*.json` and merge them, so that gates could find every
  mapping entry's part. The price: a proposer — and the LLM excerpt — saw two
  unrelated models' parts side by side, two `Housing`s with no package to tell
  them apart, and `verify api` verified whichever project was published last.
  A `Project` (`project.py`) now binds one capture to one mapping; the server
  project is matched **by name**, and a capture whose Package is not the
  project's `sysml_project` is refused on load. Guarded by
  `test_a_project_sees_only_its_own_model` and
  `test_a_capture_of_another_model_is_refused`.
- **There is no default project.** `--project`, `SYSMLCAD_PROJECT`, or an
  error listing what exists — never "the only one" or "the newest one". Which
  model gets verified is stated, not inferred; inferring it from publish order
  is exactly how the wrong one got verified. The Makefile's `PROJECT ?=
  motor_housing` is a convenience for the documented commands, not a fallback
  in the library.
- **`fixtures/requirements.json` is gone.** It was a hand-written stand-in for
  one model's requirements. Every project has a real capture now, and the
  extractor reads requirements from it — the same two requirements, verified
  (120 mm, 0.9 kg, `<=`, `motorHousing`), through the real code path. Only
  the `element_id` in a VIOLATED line changed, from `fixture-req-001` to a UUID.
- **Two models can both have a `housing`.** `CatalogPart.qualified` is
  `Gearbox::housing`, and the proposer compares that against the CAD object's
  *file plus node* rather than the bare names. Measured, not assumed: with
  containment scoring alone the baseline mapped all four gearbox housing
  attributes onto `motor_housing`, a different model's part, confidently.
- **A membership names its member under two keys.** In the API payload a
  `FeatureMembership` carries both `memberElement` and `ownedRelatedElement`
  pointing at the same `AttributeUsage`. Reading both without de-duplicating
  gives every attribute twice, which silently doubles every proposal built on
  the catalogue. Guarded by `test_each_attribute_appears_once`.
- **The SysML side's dimension lives in the attribute's TYPE.** There is no unit
  field on an `AttributeUsage`: `attribute length : LengthValue` types it
  against the library, and `catalog._VALUE_TYPES` maps that name to a pint unit.
  An unknown type name yields `None` — "cannot check", which the dimension gate
  reports as `unknown` and never as valid.
- **A backend implements `_ask` and nothing else.** The prompt, the excerpt,
  the schema, the provenance and every verification live in
  `propose_ai.LlmProposer`; `ClaudeProposer` and `OpenAIProposer` add only the
  call. That is not tidiness — those checks are the reason an arbitrary model
  can be pointed at this system at all, so a second copy of them in a backend
  would be a second chance to get them subtly wrong. Enforced by
  `test_every_backend_shares_the_verification`, which fails if a backend
  defines `propose` or `_verify` of its own. Adding a backend: one row in
  `propose.AI_PROPOSERS`, one `_ask`, one entry in `pyproject`'s extras.
- **Every validation test runs against every backend.** The `proposer` fixture
  in `tests/test_propose_ai.py` is parametrised over `BACKENDS`, so a new one
  inherits all of them the moment it is added.
- **The verification trusts types no more than names.** In plain JSON mode
  (`SYSMLCAD_OPENAI_RESPONSE_FORMAT=json_object`) nothing enforces the schema,
  so `_verify` drops a candidate that is not an object or whose confidence is
  not a number in [0, 1] -- "high" used to crash the run, 1.7 would have
  outranked every honest candidate. A truncated Claude answer
  (`parsed_output is None`, typically `max_tokens`) is dropped the same way.
- **No proposer may supply a density.** The schema has no such field, the
  prompt says not to, and `_verify` drops a candidate that carries one anyway.
  `mass` is only offered where the catalogue knows a material, so a density
  from a model could only ever override the CAD side's own -- the stale-mass
  bug described under Conventions. This changed the prompt digest; the AI
  measurements above were made with the old prompt.
- **A key in a file beats a key in the environment.** `SYSMLCAD_OPENAI_API_KEY_FILE`
  points at a file whose first line is the key; it wins over `OPENAI_API_KEY`
  when set, because naming a file is the more specific instruction and it lets
  the key live outside the repository where no `git add -A` can reach it.
  **The strip after `readline` is load-bearing** -- every editor ends a file
  with a newline, and a trailing `\n` in an Authorization header comes back as
  a 401 that reads exactly like a wrong key, sending you to look in the wrong
  place. Guarded by `test_the_trailing_newline_is_stripped`, and no error
  message or dropped-candidate reason in that module may carry the key
  (`test_a_key_never_reaches_a_log_line`).
- **There is no default OpenAI model.** `SYSMLCAD_OPENAI_MODEL` is required and
  the error names it. Guessing one would run — and bill — a model the user did
  not choose. Base URL and key resolve the SDK's own way, with one exception: a
  local server (Ollama, LM Studio) ignores the key but the SDK insists on one,
  so a placeholder is supplied when `OPENAI_BASE_URL` is set and no key is.
- **No token cap on the OpenAI call.** `max_tokens` and `max_completion_tokens`
  are accepted by different servers and model generations, and sending the wrong
  one is a hard error. The schema bounds the answer, and a truncated body fails
  to parse rather than passing silently.
- **`json_schema()` is derived from the pydantic model, never hand-written.**
  The Anthropic SDK takes the model directly; OpenAI-compatible strict mode
  wants JSON Schema with `additionalProperties: false` and every property in
  `required`. Two hand-maintained schemas would drift, and the drift would
  surface as a model that suddenly cannot answer.
- **The AI proposers are optional extras, on purpose.** `anthropic` is in
  `[project.optional-dependencies] ai` (and `openai` in `openai`), not in
  `requirements.txt`: CI verifies
  geometry and must go green without an API key. `tests/test_propose_ai.py`
  drives the proposer from `fixtures/ai_response.json`, so every line of its
  validation runs offline. **Measured, not assumed: with requirements.txt
  alone, 13 tests failed** -- building the request needs pydantic (the schema
  is derived from its model) and the outage tests need the SDK's error
  classes, and neither is in requirements.txt. Those tests now skip without
  them, and CI's second step installs both SDKs and runs the AI tests again.
  Simulate the first step locally by making `pydantic`/`openai`/`anthropic`
  unimportable (a `sys.meta_path` blocker as a pytest plugin). Model id `claude-opus-5`, structured output through
  `client.messages.parse(output_format=...)`.
- **A schema guarantees the shape of an answer, not its truth.** The model can
  return a perfectly typed `cad_object` that does not exist. Every field of
  every candidate is checked against the catalogue before it becomes a proposal,
  and each rejection is recorded — a proposer that invents names systematically
  is worth knowing about.
- **Plausibility never returns `invalid`.** A part ten times over its limit is
  either a wrong mapping or a real, large violation, and choosing between those
  is a human's job. A gate that guessed would be deciding a verdict, which is
  exactly what gates must not do.

**Test design**
- `tests/test_requirements.py` calls `run()` for every project at MODULE LEVEL
  (`RESULTS = {...}`), i.e. during test collection. It deliberately runs
  against the captures — switching it to `"api"` would make every pytest run
  require a live server. It pins the known gaps (only `MinBoreRadius`), and
  `EXPECTED` pins every requirement id per project: a requirement that
  vanished from both the verdicts and the gaps passes every other test.
- `tests/test_verify.py` pins the evaluation semantics (three verdicts,
  tolerance, unit conversion, dimension mismatch) with no geometry and no
  server. A wrong verdict is the one bug this system cannot tolerate. It also
  pins the report's words -- a `>=` violation reads "under by 1 mm", not
  "over by -1 mm" -- and, on a copied project, that a typo'd `args:` or an
  unreadable `tolerance:` costs one gap, not the run.
- `tests/test_extract.py` reconstructs the element graph synthetically from a real
  `%publish` dump. It runs without network access.
- `tests/test_step_adapter.py` is what holds the two measurement vocabularies
  together: `test_both_adapters_measure_the_same` measures the same part once
  from the script and once from its STEP export. It also pins the refusals —
  ambiguous node name, missing material, inch-authored file — because each of
  those is a case where a plausible wrong number would be worse than a gap.
- Several tests read the **committed** `projects/*/mapping.yaml` on purpose
  (`test_the_committed_mapping_passes_every_gate`, `test_requirements.py`).
  That means editing that file while a test run is in flight produces a real
  failure, which is the intended behaviour and not a flake — but it is worth
  knowing before you go hunting for one.
- `make clean` removes caches with
  `find . -name __pycache__ -type d -prune -exec rm -rf {} +`. Do not put the
  `**/__pycache__` glob back: `sh` does not expand it, so the rule quietly
  cleaned nothing.

## Deliberate simplifications (1–5 are documented at the top of extract.py)

1. **The measured quantity comes from `mapping.yaml`, not from the constraint
   expression.** `housing.length <= maxLength` is not parsed; the mapping's
   `attribute:` and `requirement:` keys carry that link instead.
   Cost: if someone points the constraint at a different attribute, it goes
   unnoticed. Closing it means resolving the `FeatureChainExpression` — the
   next extractor step.
2. One comparison per requirement only. A compound constraint is **not
   extracted** and becomes a gap -- it used to be reduced to its first
   comparison with a stdout warning, which checks one bound and reports the
   whole requirement as passed.
3. Expressions are not evaluated, only their parts are read
   (`length + width <= 200` would be wrong). → phase 6 (SMT).
4. Extraction searches the subgraph reachable from the `RequirementDefinition`
   for exactly one comparison operator, one literal, and one library element
   with a `declaredShortName`. None, or more than one, of any of them is a
   skip reason, and the run reports it as a gap. `_UPWARD_FIELDS` prevents drifting into
   neighbouring requirements — guarded by `test_requirements_stay_separate`.
5. `requirement_id` = `declaredShortName` or `declaredName` of the definition.
   `mapping.yaml` and the fixture use the same keys (`MaxLength`, `MaxMass`).
   Note `models/motor_housing.sysml` deliberately carries **no** short names:
   `<'REQ001'>` would make the id `REQ001` and match nothing in the mapping.
**No longer a simplification:** the requirement's *subject* is now resolved
through the model's `satisfy` link rather than guessed from the first
`ReferenceUsage` in the subtree. See `extract.resolve_satisfies`. A definition
satisfied by several parts is checked once per part; it used to keep only the
last `satisfy` in the payload, and the other parts were never checked and never
reported. The report labels such rows `MaxMass@cover`, and the uniqueness gate
counts entries per (requirement, part), exactly as `for_requirement` looks
them up -- which also prefers a confirmed entry over an unconfirmed one for
the same pair, whatever the file order.

**No longer a hole:** an assembly script's components were unaddressable, so a
component's mass could only be had by writing a density into `mapping.yaml`.
`gearbox#Housing` now calls `build_housing()` and the density comes from the
script. Side effect worth knowing: two gold-set entries that no proposer could
ever reach — their only correct answer required inventing a density — became
reachable, and the baseline went from 11/13 to **13/13 with zero false
positives**. Read that against a set the baseline was tuned on: the remaining
misses were an artefact of the mapping, not of the matcher.

**No longer a hole:** the confirmation gate used to cover `attributes:` only —
a `parts:` entry was used whatever its status said, and that status was never
validated. Both are fixed: `PartMapping.usable` exists, `load_mapping()`
validates it, and `verify._evaluate` reports an unconfirmed part as a gap.
Set the motorHousing part entry to `status: proposed` and the run now says
`0 compliant … 2 not checked`.

## Conventions

- **A value in `mapping.yaml` is a design error, not a convenience.** The
  mapping holds the *correspondence between two models*; a density is a *fact
  about a part* and belongs in one of the models. The gearbox mass used to carry
  `args: {density_g_per_cm3: 2.70}`, because a component was only reachable
  through the STEP export and STEP carries no material. Measured consequence:
  switch `cad/gearbox.py` to plastic (1.36) and the check kept reporting the
  aluminium mass -- 0.6457 kg instead of 0.3252 kg, a factor of two, passing
  every gate, because dimension, existence, uniqueness and magnitude were all
  fine. `Build123dAdapter` now addresses `module#Component` (mirroring the STEP
  adapter's `#`), reaching `build_housing()` in the script that declares the
  material. No mapping entry carries a density any more, and
  `test_the_committed_mapping_carries_no_density` keeps it that way.
- **Stable identity:** CAD mappings point at named module parameters
  (`LENGTH_MM`) or named measurement methods, NEVER at face or edge indices (the
  topological naming problem).
- **Units:** exactly one `pint` registry, in `units.py`. Two registries produce
  quantities that cannot be compared.
- **Explicit measurement semantics:** `bbox_size(axis="X")` is not the same thing
  as a named feature dimension. This is spelled out in `mapping.yaml` under `note`.
- `Requirement` is frozen. Never mutate one — build a new instance instead.
  `verify.run()` does that when it stamps the mapped attribute name onto the
  requirement it is about to evaluate.
- **One CAD seam:** nothing outside `src/sysmlcad/adapters/` may import
  build123d, FreeCAD, or any other geometry kernel. Everything above the seam
  speaks `CadAdapter` and pint quantities. Proven, not asserted: pointing the
  `motorHousing` entry at `fixtures/step/motor_housing.step` with
  `adapter: step` gives the same two verdicts (118 mm, 0.7429 kg) and changes
  only the recorded `cad state`, to `step:2381653212890c49`. One honest
  difference: the mass entry then needs `args: {density_g_per_cm3: 2.70}`,
  because the STEP export carries no material and the adapter reports a gap
  rather than assuming aluminium.
- **The measurement vocabulary exists twice, on purpose.** `measurements.py`
  serves the step adapter; `Build123dAdapter` keeps its own copy because adding
  STEP support was an add-on and rewiring working code is how add-ons lose
  features. `test_both_adapters_measure_the_same` enforces the invariant a
  shared module would have guaranteed. Merging them is a separate step.
- **An ambiguous CAD node name is an error, not a choice.** If a name matches
  two nodes the adapter raises `Unsupported`. Taking the first would be the same
  class of bug as substituting a value: a plausible number from the wrong object.
- **Adapters report gaps, never substitute values.** `Unsupported` is the
  answer to "this backend cannot measure that", and the run records it as a
  gap (SRS FREQ-2).
- **Ownership, not merging:** the mapping's `direction` field
  (`sysml_owns` / `cad_owns` / `both`) decides who may write a value. SysML
  owns limits, CAD owns actual values. Nothing writes yet; the field exists so
  that enabling writes is a behaviour change, not a schema migration.
- **AI proposes, never evaluates.** An AI component may propose mappings and
  speak natural language. Once a mapping is confirmed it is an ordinary
  deterministic rule and its origin no longer influences any result
  (SRS FREQ-5, NFREQ-1). The slides read as if the AI does the verification —
  it must not.
- **Two stores, and only one of them can change a verdict.** `mapping.yaml` is
  design intent: hand-written, commented, reviewed, and the only mapping a run
  reads. `proposals.yaml` is machine-written and read by no run at all. That
  separation is what makes FREQ-5 structural instead of a matter of discipline —
  a proposer physically cannot influence a result, because nothing that computes
  one opens its file.
- **Gates check the assignment; the engine checks satisfaction.** `make gates`
  and `make verify` answer different questions and must never be merged. A
  correctly mapped part that is too long passes the gates and fails
  verification, and that is the case the whole system exists to report.
- **A proposal explains itself, accurately.** FREQ-4 asks for a rationale;
  a rationale that misstates its evidence is worse than none, because it
  survives a review it should not survive. The baseline says which name matched
  and with what score, and refuses to claim a "naming match" below 0.6.
- **The mapping is YAML and lives in git; the evidence log will be SQLite.**
  The mapping is design intent and belongs in review (FREQ-3 requires it be
  human-readable and version-controllable). The append-only run log is the
  thing that wants a database. Two stores, two jobs.

## Verified reference run

```
$ make verify                              # PROJECT=motor_housing, LENGTH_MM = 118.0
project      : motor_housing
source       : fixture
cad state    : build123d:bdaee4cff5d3ddfa
mapping      : f2bf5647e29f56f6

ID         Attribute        Measured          Limit      Deviation  Status
MaxLength  length                118 mm            120 mm             -2 mm  OK
MaxMass    mass               0.7429 kg            0.9 kg        -0.1571 kg  OK
2 compliant, 0 within tolerance, 0 violated, 0 not checked   → exit 0

$ sed -i 's/LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
$ make verify
MaxLength  length                123 mm            120 mm             +3 mm  VIOLATED
  VIOLATED MaxLength: length = 123 mm <= 120 mm is false (over by 3 mm; ...)
                                                             → exit 1

# same 123 mm part, with `tolerance: "5 mm"` on the MaxLength mapping entry
MaxLength  length                123 mm            120 mm             +3 mm  TOLERANCE
  TOLERANCE MaxLength: ... inside the agreed tolerance of 5 mm   → exit 0
```

All three reproduced on 2026-09-26, digests included (the mapping digest
moved from `a4b11cc2…` when the mapping moved into `projects/`). The `cad state` and
`mapping` digests change when the geometry or the mapping changes. That is what
makes a verdict citable rather than merely printed.

The two questions kept apart, on the same mapping:

```
$ make gates                               # is the MAPPING sound?
part.attribute                dimension  existence  uniqueness  plausibility  status
motorHousing.length                  ok         ok          ok            ok  valid
motorHousing.mass                    ok         ok          ok            ok  valid
2 valid, 0 unknown, 0 invalid                                        → exit 0

# point the mass attribute at bbox_size instead:
motorHousing.mass                  FAIL         ok          ok             ?  invalid
  INVALID motorHousing.mass [dimension] bbox_size yields [length],
          but mass : MassValue is [mass]                             → exit 1

$ make verify                              # ... and the run still reports the rest
MaxLength  length                118 mm            120 mm             -2 mm  OK
1 compliant, 0 within tolerance, 0 violated, 1 not checked
  NOT CHECKED MaxMass: dimension [length] does not match [mass]
              -- a mapping fault, diagnosed by `make gates`          → exit 0
```

One bad mapping entry is one unchecked requirement, not a lost run.

## Roadmap

Stages, rationale, and open architectural questions are in
**[ROADMAP.md](ROADMAP.md)**. In short: phases 0–3 and stages A, A2, E and H are
done; what remains is B (change-impact analysis), C (evidence log and reports),
D (MCP server), F (FreeCAD adapter) and G (ownership-gated writes).

Ordering that must not be broken: **gates before writes, gates before AI,
adapter seam before FreeCAD.** The middle one is now satisfied rather than
merely planned — every proposal passes `gates.py` before it is stored, and a
human before it is used.

The target system is specified in `goal_spec.txt` (SRS v0.1) and the HNI/IEM
use-case slides; ROADMAP.md records where this project deliberately deviates
from them, and why.

**The one point from it that is easiest to get wrong:**
mapping validity and requirement satisfaction are two separate questions. Gates
check the *assignment* (dimension, existence, uniqueness, plausibility); the
verification engine checks *satisfaction*. A correctly mapped part that is too
long is a violation, not a bad mapping.
