# SysML v2 → CAD: Proof of Concept

One continuous thread from a SysML v2 requirement to a red CI pipeline.
Deliberately narrow: one part, two requirements, a hardcoded mapping.

**Status:** Stage A complete, verified end to end.

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

```
ID         Attribute        Measured          Limit      Deviation  Status
MaxLength  length                123 mm            120 mm             +3 mm  VIOLATED
MaxMass    mass               0.7753 kg            0.9 kg        -0.1247 kg  OK
1 compliant, 0 within tolerance, 1 violated, 0 not checked

  VIOLATED MaxLength: length = 123 mm <= 120 mm is false (over by 3 mm;
  source 72f3b6a1-..., bbox_size({'axis': 'X'}) on build123d:motor_housing)
Exit: 1
```

Exit 1 turns the pipeline red. That is the milestone this PoC exists to demonstrate.

A verdict is three-valued, not a boolean. Give the `MaxLength` mapping entry a
`tolerance: "5 mm"` and the same 123 mm part reports `TOLERANCE` and exits 0 —
still visible in the report, but not a failure. "Over the limit but inside what
we agreed" is the case engineers actually negotiate over, and a boolean cannot
express it.

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
mapping/mapping.yaml          parts ↔ CAD objects, attributes ↔ measurements
fixtures/step/                committed STEP fixtures for the step adapter
src/sysmlcad/
├── config.py                 SYSML_API_URL from the environment
├── units.py                  exactly one pint registry
├── model.py                  Requirement, Verdict, RunContext, Run
├── sysml_client.py           REST client, all_elements() paginates
├── extract.py                API or fixture → Requirements, incl. satisfy links
├── mapping.py                loads and resolves mapping.yaml
├── verify.py                 evaluation, report, exit code
├── explore.py                debugging tool for API payloads
├── explore_cad.py            what is inside a STEP file
└── adapters/
    ├── __init__.py           CadAdapter protocol -- the CAD seam
    ├── measurements.py       the four methods, over a shape
    ├── build123d_adapter.py  code-CAD: scripts with named parameters
    └── step_adapter.py       CAD files any system exported
tests/                        test_extract.py, test_requirements.py, test_verify.py
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

## Using a real CAD file

The build123d path needs the part as a Python script. The step adapter takes a
file straight out of a CAD system — FreeCAD, CATIA, Creo, NX, SolidWorks and
Onshape all export STEP, and no extra dependency is needed to read it.

First look inside the file. The node names are the addresses, and there is no
other way to learn them:

```bash
make explore-cad FILE=fixtures/step/gearbox.step
```

```
node                               kind         volume [mm3]            bbox X/Y/Z [mm]
Gearbox                            assembly        239151.15    90.00 /  60.00 /  46.00
   Housing                         part            207957.52    90.00 /  60.00 /  40.00
   Cover                           part             31193.63    90.00 /  60.00 /   6.00

reference strings for mapping.yaml:
    cad_object: fixtures/step/gearbox.step#Housing
    cad_object: fixtures/step/gearbox.step#Cover
```

Then point a mapping at it. `#` selects one node; without it the whole file is
measured, so an assembly's mass and bounding box aggregate over its parts:

```yaml
parts:
  - sysml_part: motorHousing
    adapter: step
    cad_object: fixtures/step/gearbox.step#Housing
    status: confirmed

attributes:
  - sysml_part: motorHousing
    attribute: mass
    requirement: MaxMass
    method: mass
    args: {density_g_per_cm3: 2.70}   # STEP rarely carries a material
    direction: cad_owns
    status: confirmed
```

**What a STEP file cannot give you:** named parameters. `LENGTH_MM` exists only
in the script — a STEP file is baked geometry, so `parameter()` returns None and
nothing can be written back parametrically. That is what the FreeCAD adapter is
for. Everything measurable — geometry, assembly tree, material where the
exporter wrote one — the step adapter already covers.

Two things it refuses rather than guesses: a node name matching more than one
node, and `mass` on a part with no material and no density override. Both are
reported as gaps.

## Next steps

Stage B: change-impact analysis — given a change on either side, derive the
affected requirements and verification cases from the model links instead of
estimating them, and report the link path that produced each one. It needs no
CAD write access and no new infrastructure.

Then C (evidence log and reports), D (MCP server), E (gates and human
confirmation), F (FreeCAD adapter), G (ownership-gated writes), H (AI mapping
proposals). Order that must not be broken: **gates before writes, gates before
AI, adapter seam before FreeCAD.** Details and rationale in
[ROADMAP.md](ROADMAP.md).
