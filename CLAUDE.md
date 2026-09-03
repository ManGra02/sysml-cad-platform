# CLAUDE.md — SysML v2 ↔ CAD verification PoC

## Goal
Check SysML v2 requirements automatically against CAD geometry. CI turns red when
the CAD model violates a system requirement. Later: a mapping store, AI-assisted
mapping proposals, bidirectional sync, SMT-based verification.

**Status: stages A and A2 complete, re-verified against the code on
2026-09-03.** The full chain runs end to end: SysML v2 API → extractor → CAD
adapter → verdict → exit code. The server side runs on the
`hni-ase/SysML-v2-API-Services` fork. 38 tests pass, and all three reference
runs at the bottom of this file reproduce exactly, digests included.

Stage A re-anchored the mapping on *parts* (resolved through the model's own
`satisfy` link), put a `CadAdapter` seam under the CAD side, made verdicts
three-valued, and made every run record the model states it came from. Stage A2
put a STEP adapter under the same seam, so a file exported by any CAD system is
measurable — with no new dependency, because build123d already brings OCCT.

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
make explore-cad FILE=x.step    # what is inside a STEP file: node names, sizes
make step-fixtures              # regenerate fixtures/step/ (they are committed)
python -m sysmlcad.verify api   # same as make verify-api
make test                       # pytest, JUnit XML to out/ (38 tests)
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
                   step/*.step        (committed STEP fixtures)
mapping/           mapping.yaml       (schema v2: parts ↔ CAD objects,
                                       attributes ↔ measurements)
src/sysmlcad/      config, units, model, sysml_client, extract, mapping,
                   verify, explore
src/sysmlcad/adapters/   __init__.py (CadAdapter protocol),
                         build123d_adapter.py, step_adapter.py,
                         measurements.py (vocabulary over a Shape)
src/sysmlcad/explore_cad.py   what is inside a STEP file
tests/             test_extract.py, test_requirements.py, test_verify.py,
                   test_step_adapter.py
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
or an `Unsupported` from the adapter. Gaps are reported and do not fail the
run. FREQ-2: report the gap, never substitute a value.

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

**API details**
- `/projects/{id}/commits/{cid}/elements` paginates — 100 per page by default,
  and the client asks for `page[size]=200`. The next page is in the Link header.
  `SysMLClient.all_elements()` follows it; `elements()` returns the first page
  only and exists for probing.
- `explore.py` has a `depth > 8` limit in `walk()`, which truncates the path to
  the unit. Raise it when debugging.

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
6. **The confirmation gate covers `attributes:` only.** `AttributeMapping.usable`
   demands `status: confirmed`, and `load_mapping()` validates `direction` and
   `status` for attribute entries. A `parts:` entry is used no matter what its
   own status says, and that status is never validated — set the motorHousing
   part entry to `status: proposed` and the run still produces two verdicts.
   That is a hole in FREQ-5; closing it belongs to stage E (gates and
   confirmation), which is where the confirmation record is designed anyway.

**No longer a simplification:** the requirement's *subject* is now resolved
through the model's `satisfy` link rather than guessed from the first
`ReferenceUsage` in the subtree. See `extract.resolve_satisfies`.

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

## Roadmap

Stages, rationale, and open architectural questions are in
**[ROADMAP.md](ROADMAP.md)**. In short: phases 0–3 and stages A and A2 are done;
stage B (change-impact analysis) is next, then C (evidence log and reports),
D (MCP server), E (gates and confirmation), F (FreeCAD adapter),
G (ownership-gated writes), H (AI mapping proposals).

Ordering that must not be broken: **gates before writes, gates before AI,
adapter seam before FreeCAD.**

The target system is specified in `goal_spec.txt` (SRS v0.1) and the HNI/IEM
use-case slides; ROADMAP.md records where this project deliberately deviates
from them, and why.

**The one point from it that is easiest to get wrong:**
mapping validity and requirement satisfaction are two separate questions. Gates
check the *assignment* (dimension, existence, uniqueness, plausibility); the
verification engine checks *satisfaction*. A correctly mapped part that is too
long is a violation, not a bad mapping.
