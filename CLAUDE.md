# CLAUDE.md — SysML v2 ↔ CAD verification PoC

*German original: [CLAUDE_de.md](CLAUDE_de.md).*

## Goal
Check SysML v2 requirements automatically against CAD geometry. CI turns red when
the CAD model violates a system requirement. Later: a mapping store, AI-assisted
mapping proposals, bidirectional sync, SMT-based verification.

**Status: stage A complete and verified.** The full chain runs end to end:
SysML v2 API → extractor → CAD adapter → verdict → exit code. The server side
runs on the `hni-ase/SysML-v2-API-Services` fork.

Stage A re-anchored the mapping on *parts* (resolved through the model's own
`satisfy` link), put a `CadAdapter` seam under the CAD side, made verdicts
three-valued, and made every run record the model states it came from.

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
make cad                        # CAD script, writes out/motor_housing.step
make verify                     # verify against fixtures/requirements.json
python -m sysmlcad.verify api   # verify against the live API server
make test                       # pytest, JUnit XML to out/
python -m sysmlcad.explore      # element dump to out/elements.json
python -m sysmlcad.explore MaxLength   # tree of one requirement
```

**On the host (needs Docker access):**
```bash
make api        # build/start sysml-api
make jupyter    # Jupyter container, http://localhost:8888/?token=sysmlcad
make logs
make down
make up         # CAUTION: starts EVERYTHING including dev and jupyter. Not
                # needed in the devcontainer workflow -- `make api` is enough.
```
NEVER run `make venv` in the devcontainer — the virtualenv already exists in the
image at `/opt/venv`.

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
cad/               motor_housing.py  (build123d)
fixtures/          requirements.json  (stand-in + regression test)
mapping/           mapping.yaml       (schema v2: parts ↔ CAD objects,
                                       attributes ↔ measurements)
src/sysmlcad/      config, units, model, sysml_client, extract, mapping,
                   verify, explore
src/sysmlcad/adapters/   __init__.py (CadAdapter protocol),
                         build123d_adapter.py
tests/             test_extract.py, test_requirements.py, test_verify.py
pyproject.toml     package metadata + pytest config (pytest.ini is gone)
out/               STEP, JUnit XML, dumps (gitignored)
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
- There is no official image. We build our own on `sbtscala/scala-sbt` with JDK 11.
- The JDBC URL is **hardcoded** to `localhost:5432` in
  `conf/META-INF/persistence.xml` and cannot be overridden via a system property.
  The Dockerfile patches it to `postgres:5432` with `sed`.
- `hbm2ddl.auto` is patched from `create-drop` to `update` with `sed` — otherwise
  the schema is dropped on every stop.
- `sbt run` (dev mode) dies on EOF on stdin, even with `stdin_open`/`tty`.
  Fix: `sbt stage`, and CMD starts
  `/app/target/universal/stage/bin/sysml-v2-api-services` (spelled out, because a
  glob would also match the `.bat` file).
- Play's `AllowedHostsFilter` rejects `Host: sysml-api:9000` with a 400.
  Flag: `-Dplay.filters.hosts.allowed.0='.'`
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
- `/projects/{id}/commits/{cid}/elements` paginates at 100. The next page is in
  the Link header. `SysMLClient.all_elements()` follows it; `elements()` does not.
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
- `make clean` uses `**/__pycache__`, which `sh` does not expand. To clean up
  manually, use:
  `find . -name __pycache__ -type d -exec rm -rf {} +`

## Deliberate simplifications (documented at the top of extract.py)

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

## Conventions

- **Stable identity:** CAD mappings point at named module parameters
  (`LENGTH_MM`) or named measurement methods, NEVER at face or edge indices (the
  topological naming problem).
- **Units:** exactly one `pint` registry, in `units.py`. Two registries produce
  quantities that cannot be compared.
- **Explicit measurement semantics:** `bbox_size(axis="X")` is not the same thing
  as a named feature dimension. This is spelled out in `mapping.yaml` under `note`.
- `Requirement` is frozen; extend it via `dataclasses.replace`.
- **One CAD seam:** nothing outside `src/sysmlcad/adapters/` may import
  build123d, FreeCAD, or any other geometry kernel. Everything above the seam
  speaks `CadAdapter` and pint quantities.
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

The `cad state` and `mapping` digests change when the geometry or the mapping
changes. That is what makes a verdict citable rather than merely printed.

## Roadmap

Stages, rationale, and open architectural questions are in
**[ROADMAP.md](ROADMAP.md)**. In short: phases 0–3 and stage A are done;
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
