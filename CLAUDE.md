# CLAUDE.md — SysML v2 ↔ CAD verification PoC

*German original: [CLAUDE_de.md](CLAUDE_de.md).*

## Goal
Check SysML v2 requirements automatically against CAD geometry. CI turns red when
the CAD model violates a system requirement. Later: a mapping store, AI-assisted
mapping proposals, bidirectional sync, SMT-based verification.

**Status: phase 1 complete and verified.** The full chain runs end to end:
SysML v2 API → extractor → build123d measurement → verdict → exit code.
The server side runs on the `hni-ase/SysML-v2-API-Services` fork.

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
docker/            docker-compose.yml, jupyter.Dockerfile
                   (no api-services.Dockerfile any more -- the fork ships one)
vendor/            hni-ase/SysML-v2-API-Services (git clone, not in the repo)
.env               PLAY_SECRET (not in the repo, see below)
.github/workflows/ verify.yml -- CI runs against the FIXTURE, not the API
                   (deliberate: CI must be able to go green without a server)
models/            motor_housing.sysml
notebooks/         01_publish_motor_housing.ipynb
cad/               motor_housing.py  (build123d)
fixtures/          requirements.json  (stand-in + regression test)
mapping/           mapping.yaml       (requirement ↔ measurement method)
src/sysmlcad/      config, units, model, sysml_client, extract, measure, verify, explore
tests/             test_extract.py, test_requirements.py
out/               STEP, JUnit XML, dumps (gitignored)
```

## Data flow

1. `extract.load("api")` → `SysMLClient.all_elements()` (paginated) →
   `elements_to_requirements()` → `Requirement(id, operator, limit: pint.Quantity)`
2. `mapping.yaml` supplies, per `requirement_id`: `cad_module`, `method`, `args`, `property`
3. `measure.load_part()` imports the CAD module, calls `build()`, measures
4. `Requirement.check()` compares with a dimension check → `Verdict`
5. `verify.report()` → table, exit 0/1

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
- Python 3.14: `ezdxf` has no cp314 wheels and runs pure-Python. That affects DXF
  only, not STEP. `lib3mf` DeprecationWarnings are expected and harmless.
- **build123d 0.11:** `export_step(part, path)` is a MODULE FUNCTION, not a method
  on the part. Older examples on the web show `part.export_step(...)`.
- Measurements: `part.volume` (mm³), `part.bounding_box().size.X`,
  `part.center(CenterOf.MASS)`, `len(part.faces())`.

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
- `tests/test_requirements.py` calls `run()` at MODULE LEVEL (`VERDICTS = run()`),
  i.e. during test collection. It deliberately runs against the fixture —
  switching it to `"api"` would make every pytest run require a live server.
- `tests/test_extract.py` reconstructs the element graph synthetically from a real
  `%publish` dump. It runs without network access.
- `make clean` uses `**/__pycache__`, which `sh` does not expand. To clean up
  manually, use:
  `find . -name __pycache__ -type d -exec rm -rf {} +`

## Deliberate simplifications (documented at the top of extract.py)

1. **The measured quantity comes from `mapping.yaml`, not from the constraint
   expression.** `housing.length <= maxLength` is not parsed.
   Cost: if someone points the constraint at a different attribute, it goes
   unnoticed. → phase 4.
2. One comparison per requirement only; compound constraints are reduced to the
   first one (with a warning).
3. Expressions are not evaluated, only their parts are read
   (`length + width <= 200` would be wrong). → phase 6 (SMT).
4. Extraction searches the subgraph reachable from the `RequirementDefinition`
   for: the first comparison operator, the first literal, and the first library
   element with a `declaredShortName`. `_UPWARD_FIELDS` prevents drifting into
   neighbouring requirements — guarded by
   `test_mehrere_anforderungen_bleiben_getrennt`.
5. `requirement_id` = `declaredShortName` or `declaredName` of the definition.
   `mapping.yaml` and the fixture use the same keys (`MaxLength`, `MaxMass`).

## Conventions

- **Stable identity:** CAD mappings point at named module parameters
  (`LENGTH_MM`) or named measurement methods, NEVER at face or edge indices (the
  topological naming problem).
- **Units:** exactly one `pint` registry, in `units.py`. Two registries produce
  quantities that cannot be compared.
- **Explicit measurement semantics:** `bbox_size(axis="X")` is not the same thing
  as a named feature dimension. This is spelled out in `mapping.yaml` under `note`.
- `Requirement` is frozen; extend it via `dataclasses.replace`.

## Verified reference run

CLI output is still German (`verletzt` = violated), shown verbatim:

```
$ python -m sysmlcad.verify api            # LENGTH_MM = 118.0
MaxLength length  118 mm  <= 120 mm  OK
MaxMass   mass   0.7429 kg <= 0.9 kg  OK    → exit 0

$ sed -i 's/LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
$ python -m sysmlcad.verify api
MaxLength verletzt: length = 123 mm <= 120 mm ist falsch  → exit 1
```

## Roadmap

Phases, rationale, and open architectural questions are in **[ROADMAP.md](ROADMAP.md)**.
In short: phases 0–3 are done; phase 4 (mapping store, deterministic gates, AI
hypotheses) is next.

**The one point from it that is easiest to get wrong:**
mapping validity and requirement satisfaction are two separate questions. Gates
check the *assignment* (dimension, existence, uniqueness, plausibility); the
verification engine checks *satisfaction*. A correctly mapped part that is too
long is a violation, not a bad mapping.
