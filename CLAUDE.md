# CLAUDE.md — SysML v2 ↔ CAD verification PoC

## Goal
Check SysML v2 requirements automatically against CAD geometry. CI turns red when
the CAD model violates a system requirement. Later: a mapping store, AI-assisted
mapping proposals, bidirectional sync, SMT-based verification.

**Status: stages A, A2, E and H complete; 156 tests pass.** The verification
chain runs end to end (SysML v2 API → extractor → CAD adapter → verdict → exit
code), and on top of it the mapping can now be *proposed*: a catalogue of both
sides, four gates over any proposed entry, a proposal store, a human
confirmation step that writes into `mapping.yaml`, a stdlib baseline proposer
and a Claude one. The server side runs on the `hni-ase/SysML-v2-API-Services`
fork. All three reference runs at the bottom of this file reproduce exactly,
digests included.

Two models are published and captured: `MotorHousing` (one part) and `Gearbox`
(three parts, ten attributes, an interface dimension and an assembly mass
budget). The baseline proposer scores **11/13 hit@1 with 2 false positives**
against `fixtures/gold_mapping.yaml`.

One caveat stated plainly: the AI proposer has never been run for real -- there
are no credentials in this environment -- so its column on the scoreboard is
empty. It is wired, tested against a recorded response, and unmeasured.

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
make cad                        # CAD scripts, writes out/motor_housing.step
make verify                     # verify against fixtures/requirements.json
make verify-api                 # verify against the live API server
make gates                      # is the MAPPING sound? (not: is the design ok)
make catalog                    # what exists on each side, as data
make explore-cad FILE=x.step    # what is inside a STEP file: node names, sizes
make step-fixtures              # regenerate fixtures/step/ (they are committed)
python -m sysmlcad.verify api   # same as make verify-api
make test                       # pytest, JUnit XML to out/ (156 tests)

# Mapping proposals -- nothing here can change a verdict
make propose                    # baseline proposer -> mapping/proposals.yaml
make propose AI=claude          # ask Claude instead (needs the SDK + a key)
make propose AI=openai          # ...or any OpenAI-protocol server, local too
make proposals                  # what is waiting for a decision
make confirm ID=p-01            # gate it again, then write it into mapping.yaml
make propose-score              # hit rate against fixtures/gold_mapping.yaml
python -m sysmlcad.explore      # element dump to out/elements.json
python -m sysmlcad.explore MaxLength   # tree of one requirement
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
.github/workflows/ verify.yml -- CI runs against the FIXTURE, not the API
                   (deliberate: CI must be able to go green without a server)
models/            motor_housing.sysml
notebooks/         01_publish_motor_housing.ipynb
cad/               motor_housing.py, gearbox.py (two-part assembly),
                   export_fixtures.py (writes fixtures/step/)
fixtures/          requirements.json  (stand-in + regression test)
                   elements.json      (captured API response -- the offline
                                       source for the catalogue and its tests;
                                       moved out of out/, which `make clean`
                                       empties)
                   gold_mapping.yaml  (the answer key for proposer scoring)
                   ai_response.json   (a CONSTRUCTED model response, so the AI
                                       proposer's validation is testable with
                                       no key; says so in its own _comment)
                   step/*.step        (committed STEP fixtures)
mapping/           mapping.yaml       (schema v2: parts ↔ CAD objects,
                                       attributes ↔ measurements)
                   proposals.yaml     (machine-written; committed, because a
                                       rejection is worth remembering the next
                                       time a proposer suggests the same pair.
                                       No verification run opens it)
src/sysmlcad/      config, units, model, sysml_client, extract, mapping,
                   verify, explore
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
                   test_step_adapter.py, test_catalog.py, test_gates.py,
                   test_confirm.py, test_propose.py, test_propose_ai.py,
                   test_propose_openai.py
pyproject.toml     package metadata + pytest config (pytest.ini is gone)
out/               STEP, JUnit XML, dumps. Only *.step and *.xml are
                   gitignored; out/elements.json and out/relevant.txt are
                   committed captures of a real API response, kept as
                   reference payloads for extractor work
```

## Data flow

1. `extract.load_with_context("api")` → `SysMLClient.all_elements()`
   (paginated) → `elements_to_requirements()`, which first runs
   `resolve_satisfies()` to learn which PartUsage each requirement is about →
   `Requirement(id, subject, operator, limit: pint.Quantity)` plus the project
   and commit ids
2. `mapping.load_mapping()` → `parts:` (SysML part ↔ adapter + CAD object) and
   `attributes:` (SysML attribute ↔ measurement method, unit, direction,
   tolerance, status)
3. `verify.AdapterPool` instantiates the adapter named by the part entry;
   `adapter.measure(obj, method, args)` returns a pint quantity
4. `Requirement.evaluate()` compares with a dimension check →
   `(status, deviation)` → `Verdict`
5. `verify.run()` → `Run(context, verdicts, gaps)`; `report()` → table, exit 0/1

An unevaluable requirement becomes a **gap**, not a pass: no confirmed mapping,
an `Unsupported` from the adapter, or a `DimensionMismatch` (which is a mapping
fault, so it is reported as a gap here and diagnosed by `make gates` — letting
it escape would take every other verdict in the run down with it). Gaps are
reported and do not fail the run. FREQ-2: report the gap, never substitute a
value.

**How a mapping entry comes to exist** — the second flow, which cannot touch the
first:

1. `catalog.load_catalog()` → `Catalog(parts, targets)`: SysML part usages with
   their attributes and *value types*, CAD objects with the measurements they
   actually support. One excerpt, three consumers (gates, proposers, explorers)
2. a `Proposer` (`DifflibProposer`, `ClaudeProposer`) turns that into
   `Proposal`s with a confidence and a rationale (FREQ-4)
3. `propose.gate()` runs every candidate through `gates.py` **before storing
   it**; the rejects are reported, not silently dropped
4. survivors go to `mapping/proposals.yaml` with `status: proposed`. No
   verification run opens that file
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
  -Dplay.filters.hosts.allowed.0=. -Dplay.http.secret.key=${PLAY_SECRET}`.
- The first start takes minutes (schema creation, ~8200 tables). It is ready once
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
- `Shape.cast()` on the BASE class is an `@abstractmethod` and returns `None`.
  `Shape.shape_LUT` maps to class *names* (strings), not classes. The adapter
  therefore keeps its own explicit `TopAbs_* -> build123d class` table.
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
- `/projects/{id}/commits/{cid}/elements` paginates — 100 per page by default,
  and the client asks for `page[size]=200`. The next page is in the Link header.
  `SysMLClient.all_elements()` follows it; `elements()` returns the first page
  only and exists for probing.
- `explore.py` has a `depth > 8` limit in `walk()`, which truncates the path to
  the unit. Raise it when debugging.

**Mapping proposals, gates and the AI**
- **A YAML round-tripper is not a safe way to edit `mapping.yaml`.** Measured,
  not assumed: `ruamel.yaml` 0.19.1 preserves the comments but still rewrites 38
  lines of today's file — list indentation (`  - ` becomes `- `), `tolerance:
  null` becomes an empty value, and a wrapped double-quoted note is re-wrapped
  somewhere else. `confirm.py` therefore renders the new entry as text and
  inserts it at the end of its section, leaving every existing byte alone, then
  re-parses the result and restores the original if it does not read back as
  intended. The dependency was tried and dropped; do not reintroduce it.
- **The catalogue merges every capture in `fixtures/*elements*.json`.** Two
  models are published; a catalogue showing only one would make the other's
  mapping entries look like mistakes to the existence gate. Element ids are
  UUIDs, so merging is safe.
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
  inherits all sixteen the moment it is added.
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
  validation runs offline. Model id `claude-opus-5`, structured output through
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
- `tests/test_requirements.py` calls `run()` at MODULE LEVEL (`RESULT = run()`),
  i.e. during test collection. It deliberately runs against the fixture —
  switching it to `"api"` would make every pytest run require a live server.
  It also asserts `RESULT.gaps == []`: a requirement that was silently not
  checked must not be allowed to look like a pass.
- `tests/test_verify.py` pins the evaluation semantics (three verdicts,
  tolerance, unit conversion, dimension mismatch) with no geometry and no
  server. A wrong verdict is the one bug this system cannot tolerate.
- `tests/test_extract.py` reconstructs the element graph synthetically from a real
  `%publish` dump. It runs without network access.
- `tests/test_step_adapter.py` is what holds the two measurement vocabularies
  together: `test_both_adapters_measure_the_same` measures the same part once
  from the script and once from its STEP export. It also pins the refusals —
  ambiguous node name, missing material, inch-authored file — because each of
  those is a case where a plausible wrong number would be worse than a gap.
- Several tests read the **committed** `mapping/mapping.yaml` on purpose
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
2. One comparison per requirement only; compound constraints are reduced to the
   first one (with a warning).
3. Expressions are not evaluated, only their parts are read
   (`length + width <= 200` would be wrong). → phase 6 (SMT).
4. Extraction searches the subgraph reachable from the `RequirementDefinition`
   for: the first comparison operator, the first literal, and the first library
   element with a `declaredShortName`. `_UPWARD_FIELDS` prevents drifting into
   neighbouring requirements — guarded by `test_requirements_stay_separate`.
5. `requirement_id` = `declaredShortName` or `declaredName` of the definition.
   `mapping.yaml` and the fixture use the same keys (`MaxLength`, `MaxMass`).
   Note `models/motor_housing.sysml` deliberately carries **no** short names:
   `<'REQ001'>` would make the id `REQ001` and match nothing in the mapping.
**No longer a simplification:** the requirement's *subject* is now resolved
through the model's `satisfy` link rather than guessed from the first
`ReferenceUsage` in the subtree. See `extract.resolve_satisfies`.

**No longer a hole:** the confirmation gate used to cover `attributes:` only —
a `parts:` entry was used whatever its status said, and that status was never
validated. Both are fixed: `PartMapping.usable` exists, `load_mapping()`
validates it, and `verify._evaluate` reports an unconfirmed part as a gap.
Set the motorHousing part entry to `status: proposed` and the run now says
`0 compliant … 2 not checked`.

## Conventions

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
$ python -m sysmlcad.verify                # LENGTH_MM = 118.0
source       : fixture
cad state    : build123d:bdaee4cff5d3ddfa
mapping      : a4b11cc20a9634e8

ID         Attribute        Measured          Limit      Deviation  Status
MaxLength  length                118 mm            120 mm             -2 mm  OK
MaxMass    mass               0.7429 kg            0.9 kg        -0.1571 kg  OK
2 compliant, 0 within tolerance, 0 violated, 0 not checked   → exit 0

$ sed -i 's/LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
$ python -m sysmlcad.verify
MaxLength  length                123 mm            120 mm             +3 mm  VIOLATED
  VIOLATED MaxLength: length = 123 mm <= 120 mm is false (over by 3 mm; ...)
                                                             → exit 1

# same 123 mm part, with `tolerance: "5 mm"` on the MaxLength mapping entry
MaxLength  length                123 mm            120 mm             +3 mm  TOLERANCE
  TOLERANCE MaxLength: ... inside the agreed tolerance of 5 mm   → exit 0
```

All three reproduced on 2026-09-03, digests included. The `cad state` and
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

**The one thing left before the proposer means anything:** publish
`models/gearbox.sysml` (three parts, ten attributes, written and waiting) and
capture its elements to `fixtures/gearbox_elements.json`. Until then the gold
set has two entries and cannot separate a language model from a string
matcher — both score 2/2, which says nothing about either.

The target system is specified in `goal_spec.txt` (SRS v0.1) and the HNI/IEM
use-case slides; ROADMAP.md records where this project deliberately deviates
from them, and why.

**The one point from it that is easiest to get wrong:**
mapping validity and requirement satisfaction are two separate questions. Gates
check the *assignment* (dimension, existence, uniqueness, plausibility); the
verification engine checks *satisfaction*. A correctly mapped part that is too
long is a violation, not a bad mapping.
