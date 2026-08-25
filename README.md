# SysML v2 → CAD: Proof of Concept

One continuous thread from a SysML v2 requirement to a red CI pipeline.
Deliberately narrow: one part, two requirements, a hardcoded mapping.

**Status:** Phase 1 complete, verified end to end.

*German original: [README_de.md](README_de.md).*

## Quick start

Everything runs in containers. Open the devcontainer first:

```bash
code .        # then "Reopen in Container"
```

Then, **inside the devcontainer**:

```bash
make cad      # run the CAD script, write STEP to out/
make verify   # verify against fixtures/requirements.json
make test     # pytest, JUnit XML to out/
```

None of these three need the SysML server or Jupyter. Do **not** run `make venv`
in the devcontainer — the virtualenv already ships in the image at `/opt/venv`.

For the full stack, run this **on the host** (the devcontainer has no Docker access):

```bash
make secret               # generates PLAY_SECRET in docker/.env, see below
make api                  # SysML v2 API server; first build takes ~6 min
make jupyter              # JupyterLab at http://localhost:8888/?token=sysmlcad
```

The server is ready once `Listening for HTTP` appears in the log:

```bash
docker logs -f sysml2-api
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9000/projects   # 200
```

## Publishing the model

In JupyterLab, open `notebooks/01_publish_motor_housing.ipynb` and select the
**SysML** kernel (not Python). Run the model cell, then `%publish MotorHousing`.
The first output line must read `http://sysml-api:9000`. If it says
`sysml2.intercax.com`, the model would go to the public community server instead.

Then verify against the real server from inside the devcontainer:

```bash
python -m sysmlcad.verify api
python -m sysmlcad.explore              # element dump to out/elements.json
python -m sysmlcad.explore MaxLength    # tree of a single requirement
```

## The failure case

```bash
sed -i 's/^LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
python -m sysmlcad.verify api ; echo "Exit: $?"
```

The CLI still prints German (`verletzt` = violated), verbatim:

```
MaxLength verletzt: length = 123 mm <= 120 mm ist falsch
(Quelle: 72f3b6a1-..., Methode: bbox_size({'axis': 'X'}))
Exit: 1
```

Exit 1 turns the pipeline red. That is the milestone this PoC exists to demonstrate.

## Architecture

Four containers, one Compose project, one network:

| Container | Role | Port |
|---|---|---|
| `dev` | Devcontainer, Python 3.14, virtualenv at `/opt/venv` | — |
| `sysml2-postgres` | PostgreSQL 16, database `sysml2` | 5432 |
| `sysml2-api` | SysML v2 API Services (hni-ase fork), Play/Hibernate | 9000 |
| `sysml2-jupyter` | SysML v2 kernel, `%publish` | 8888 |

**The rule everyone forgets:** container-to-container traffic uses the *service
name* (`sysml-api:9000`, `postgres:5432`), never `localhost`.
`src/sysmlcad/config.py` reads `SYSML_API_URL`; the Compose overlay sets it
accordingly. The `ports:` entries exist only so your browser can reach the
services from the host.

## Layout

```
.devcontainer/
├── devcontainer.json         references both Compose files
├── docker-compose.dev.yml    overlay: adds the dev service
└── Dockerfile                Python 3.14 (trixie) + OpenGL/X11 for OCP
docker/
├── docker-compose.yml        postgres, sysml-api, jupyter
├── jupyter.Dockerfile        conda, SysML kernel, standard library
└── .env                      PLAY_SECRET (not in git), see below
vendor/                       hni-ase/SysML-v2-API-Services (clone, not in git)
models/motor_housing.sysml    the system model, textual
notebooks/                    01_publish_motor_housing.ipynb
cad/motor_housing.py          the part as a build123d script
fixtures/requirements.json    stand-in + regression test
mapping/mapping.yaml          requirement ↔ measurement method
src/sysmlcad/
├── config.py                 SYSML_API_URL from the environment
├── units.py                  exactly one pint registry
├── model.py                  Requirement, Verdict
├── sysml_client.py           REST client, all_elements() paginates
├── extract.py                API or fixture → list of Requirements
├── measure.py                CAD property → quantity with a unit
├── verify.py                 evaluation, report, exit code
└── explore.py                debugging tool for API payloads
tests/                        test_extract.py, test_requirements.py
.github/workflows/verify.yml  CI, runs against the fixture
CLAUDE.md                     project context for Claude Code
```

## docker/.env

In production mode, Play refuses to start without a sufficiently long secret
key. Generate one once with `make secret`, or by hand:

```bash
echo "PLAY_SECRET=$(head -c 48 /dev/urandom | base64 | tr -d '\n')" > docker/.env
grep -q '^\.env$' .gitignore || echo ".env" >> .gitignore
```

**The location matters.** Compose looks for the env file in the directory of the
*first* `-f` file, which is `docker/` — not in the project root. The Makefile
could work around that with `--env-file`, but the VS Code Dev Containers
extension builds its own `docker compose` command and has no way to pass that
flag. With the file anywhere else, opening the devcontainer fails at
`docker compose config` with:

```
required variable PLAY_SECRET is missing a value
```

That happens even though the devcontainer only starts `dev` and `postgres`:
`compose config` interpolates the whole merged file, `sysml-api` included.

## Known pitfalls

The full list, with reasoning, is in **[CLAUDE.md](CLAUDE.md)** under "Solved
pitfalls". The three most common ones:

**`localhost` vs. service name.** By far the most frequent mistake. Inside the
devcontainer it is `sysml-api:9000`; on the host it is `localhost:9000`.

**SysML v2 syntax (release 0.60.1).** Imports require an explicit visibility
(`private import ISQ::*;`), and `satisfy` needs a requirement *usage*, not a
definition.

**`export_step` is a module function.** In build123d 0.11 the call is
`export_step(part, path)`, not `part.export_step(path)`. Older examples on the
web still show the method form.

## Next steps

Phase 4, in this order: mapping store (SQLite with an audit log) →
deterministic gates → only then AI-generated hypotheses. Details in
[ROADMAP.md](ROADMAP.md).
