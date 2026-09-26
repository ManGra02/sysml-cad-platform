# SysML v2 → CAD: Proof of Concept

One continuous thread from a SysML v2 requirement to a red CI pipeline.
Deliberately narrow: two small models, six requirements, and a mapping that a
human confirms entry by entry.

**Status:** Stages A, A2, E and H complete — 247 tests green. Two models are
published and verified against CAD: `MotorHousing` (one part) and `Gearbox`
(three parts, an interface dimension, an assembly mass budget). Requirements are
read from the live SysML v2 API or from a fixture; geometry is measured either
from a build123d script or from a STEP file any CAD system exported. The mapping
itself can be proposed — by a string matcher or by a language model of your
choice — gated by machine, and
confirmed by a human before anything uses it.

## Quick start

Everything runs in containers. Open the devcontainer first:

```bash
code .        # then "Reopen in Container"
```

Then, **inside the devcontainer**:

```bash
make projects              # the SysML models this repo knows: one dir each
make cad                   # run the CAD scripts, write STEP to out/
make verify                # verify the default project (motor_housing)
make verify PROJECT=gearbox   # ...or another one, against ITS mapping
make gates                 # is the MAPPING sound? (a different question)
make test                  # pytest, JUnit XML to out/ (247 tests)
make catalog               # what exists on each side, as data
make explore-cad FILE=fixtures/step/gearbox.step   # what is in a STEP file
make step-fixtures  # regenerate fixtures/step/ after changing a CAD script
```

None of these need the SysML server or Jupyter. Do **not** run `make venv`
in the devcontainer — the virtualenv already ships in the image at `/opt/venv`.

For the full stack, run this **on the host** (the devcontainer has no Docker access):

```bash
make secret               # PLAY_SECRET into docker/.env, if not there yet
make vendor               # clone the hni-ase API fork, patch hbm2ddl.auto
make api                  # SysML v2 API server; first build takes ~6 min
make jupyter              # JupyterLab at http://localhost:8888/?token=sysmlcad
```

`make api` runs `secret` and `vendor` for you, and opening the devcontainer
creates `docker/.env` by itself (`initializeCommand` in `devcontainer.json`), so
a fresh clone opens without any preparation.

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
make verify-api                         # or: python -m sysmlcad.verify -p motor_housing api
python -m sysmlcad.explore -p motor_housing             # element dump to out/elements.json
python -m sysmlcad.explore -p motor_housing MaxLength   # tree of a single requirement
```

## The failure case

```bash
sed -i 's/^LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
python -m sysmlcad.verify -p motor_housing ; echo "Exit: $?"
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

**What a run does not check, it says.** A requirement with no confirmed
mapping, a measurement the adapter cannot make, a malformed `args:` or
`tolerance:` in one entry, and a requirement the extractor cannot read (a
compound constraint, say) each become one `NOT CHECKED` line. None of them
fails the run, and none of them takes the other verdicts down with it.

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
models/
├── motor_housing.sysml       the system model, textual -- kept in step with
                              the notebook, which is what reaches the server
└── gearbox.sysml             the two-part assembly
notebooks/                    01_publish_motor_housing.ipynb, 02_publish_gearbox.ipynb
cad/
├── motor_housing.py          the reference part as a build123d script
├── gearbox.py                two-part assembly, Housing + Cover, shared bore
└── export_fixtures.py        writes fixtures/step/, `make step-fixtures`
projects/                     ONE DIRECTORY PER SYSML MODEL -- nothing shared
├── motor_housing/
│   ├── project.yaml          name + the model's Package / server project name
│   ├── mapping.yaml          parts ↔ CAD objects, attributes ↔ measurements
│   ├── elements.json         a captured API response -- the offline source
│   ├── gold_mapping.yaml     the answer key for scoring proposers on this model
│   └── proposals.yaml        machine-written; no verification run reads it
└── gearbox/                  the same five files for the gearbox
fixtures/
├── ai_response.json          a constructed model response, for offline tests
└── step/                     committed STEP fixtures for the step adapter
src/sysmlcad/
├── config.py                 SYSML_API_URL from the environment
├── units.py                  exactly one pint registry
├── model.py                  Requirement, Verdict, RunContext, Run
├── sysml_client.py           REST client, all_elements() paginates
├── extract.py                API or fixture → Requirements, incl. satisfy links
├── project.py                one model + its mapping, chosen by name, never guessed
├── mapping.py                loads and resolves mapping.yaml
├── verify.py                 evaluation, report, exit code
├── catalog.py                what exists on each side, as data
├── gates.py                  is the mapping sound (≠ is the design ok)
├── proposals.py              the proposal store
├── propose.py                Proposer protocol + the stdlib baseline
├── propose_ai.py             LlmProposer base + the Claude backend
├── propose_openai.py         any OpenAI-protocol server (local included)
├── confirm.py                human confirmation → mapping.yaml
├── score.py                  hit rate against the gold set
├── explore.py                debugging tool for API payloads
├── explore_cad.py            what is inside a STEP file
└── adapters/
    ├── __init__.py           CadAdapter protocol -- the CAD seam
    ├── measurements.py       the four methods, over a shape
    ├── build123d_adapter.py  code-CAD: scripts with named parameters
    └── step_adapter.py       CAD files any system exported
tests/
├── test_extract.py           the element graph, rebuilt from a real %publish
├── test_requirements.py      the rule runner -- runs verify() at collection
├── test_verify.py            evaluation semantics, the report, one bad entry = one gap
├── test_project.py           one model per project, and the refusals
├── test_build123d_adapter.py component addressing, material from the script
├── test_step_adapter.py      STEP reading, and both adapters agreeing
├── test_catalog.py           both sides of the excerpt
├── test_gates.py             the four gates, and what they may not conclude
├── test_confirm.py           the store, and writing YAML without rewriting it
├── test_propose.py           the baseline, and the dimension filter
├── test_propose_ai.py        every AI backend, from a recorded response
└── test_propose_openai.py    the OpenAI-protocol call, against a stub client
out/                          STEP, JUnit XML, dumps. *.step and *.xml are
                              ignored; relevant.txt and llm_request.txt are
                              committed reference payloads
.github/workflows/verify.yml  CI, runs against the fixture
CLAUDE.md                     project context for Claude Code
ROADMAP.md                    stages, rationale, open questions
goal_spec.txt                 the target system's SRS v0.1
```

## docker/.env

In production mode, Play refuses to start without a sufficiently long secret
key. Opening the devcontainer generates one automatically — `initializeCommand`
in `devcontainer.json` runs on the host before Compose and writes the file if it
is missing. On the host, `make secret` does the same, or by hand:

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

no material in the file for: Gearbox, Housing, Cover
  -> `mass` from this file is a gap, not an invented density. Measure
     it where the material is declared (a build123d script), or pass
     `args: {density_g_per_cm3: ...}` for a what-if study -- a density
     committed to mapping.yaml fails the test suite on purpose.
```

Then point a mapping at it. `#` selects one node; without it the whole file is
measured, so an assembly's mass and bounding box aggregate over its parts. A
file with several root shapes has no "whole file" -- each root is addressed by
name, and the bare path is refused:

```yaml
parts:
  - sysml_part: motorHousing
    adapter: step
    cad_object: fixtures/step/gearbox.step#Housing
    status: confirmed

attributes:
  - sysml_part: motorHousing
    attribute: length
    requirement: MaxLength
    method: bbox_size
    args: {axis: X}
    direction: cad_owns
    status: confirmed
```

**Mass needs a material, and STEP rarely carries one.** Without it the run
reports `mass` as a gap. `args: {density_g_per_cm3: ...}` makes it computable,
but a density is a fact about the part, not a correspondence between two
models -- frozen into `mapping.yaml` it keeps reporting the old mass after the
material changes. `test_the_committed_mapping_carries_no_density` therefore
refuses it in any committed mapping; use it for what-if studies, and measure
mass where the material is declared.

**What a STEP file cannot give you:** named parameters. `LENGTH_MM` exists only
in the script — a STEP file is baked geometry, so `parameter()` returns None and
nothing can be written back parametrically. That is what the FreeCAD adapter is
for. Everything measurable — geometry, assembly tree, material where the
exporter wrote one — the step adapter already covers.

Two things it refuses rather than guesses: a node name matching more than one
node, and `mass` on a part with no material and no density override. Both are
reported as gaps.

The swap is a real one, not a claim: point `motorHousing` at
`fixtures/step/motor_housing.step` instead of the script and the length verdict
comes out the same — 118 mm — with only the recorded `cad state` changing
(the mass agrees too, 0.7429 kg, given the density as a what-if). That is the
adapter seam doing its job.

## Where a mapping comes from

Writing the mapping by hand is the most tedious part of setting this up, so it
can be proposed. Nothing proposed can change a result: candidates live in their
own file, are machine-checked before a human sees them, and reach `mapping.yaml`
only through an explicit confirmation.

```bash
make catalog            # what is on each side: parts, attributes, CAD targets
make propose            # stdlib name matching -> projects/<name>/proposals.yaml
make propose AI=claude   # ask Claude instead  (pip install anthropic)
make propose AI=openai   # ...or any OpenAI-protocol server, local included
make proposals          # what is waiting for a decision
make confirm ID=p-01    # gate it again, then write it into mapping.yaml
```

A confirmation prints its gates before it writes anything:

```
p-01  motorHousing.mass  ->  build123d:motor_housing  via mass({})
proposed by baseline:difflib with confidence 0.82
  existence     valid    0.7429 kg
  dimension     valid    [mass]
  uniqueness    valid
  plausibility  valid    measured/limit = 0.825

confirmed by Vincent Hey:
  + attributes: motorHousing.mass
```

The entry is appended to `mapping.yaml` with your name and the date; every
existing byte of the file, comments included, is left exactly as it was. If the
file does not read back as intended, the original is restored and nothing is
written.

**A part stands for one CAD object.** The gates measure the object a proposal
names, and a proposal that names a different object for a part that is already
mapped is refused. It used to be gated — and, once confirmed, measured — on the
part's existing object, so a reviewer could approve `cover.mass ->
gearbox#Housing` and get the cover's own mass without noticing. If a part's
mapping is wrong, that is an edit to its `parts:` entry, in review.

**Two questions, deliberately not merged.** `make gates` asks whether the
*mapping* is sound — right dimension, measurable, unique, plausible.
`make verify` asks whether the *design* complies. A correctly mapped part that
is too long passes the first and fails the second, and that is the case the
system exists to report.

**What the AI may and may not do.** It proposes, with a confidence and a
rationale (SRS FREQ-4). Every candidate is then checked against the catalogue —
a part, attribute or CAD object it names but that does not exist is dropped and
the reason recorded, as is a confidence outside [0, 1] or a density the model
tried to supply — and then through the same four gates as any other
proposal. Once confirmed, an entry is an ordinary deterministic rule and nothing
behaves differently because a model suggested it (FREQ-5, NFREQ-1). CI never
calls it: every SDK is an optional extra and the tests drive the proposers from
a recorded response.

**Bringing your own model.** A backend supplies one method, `_ask`; the prompt,
the excerpt, the schema, the provenance and all of the verification above live
in `LlmProposer` and are shared. Two ship today:

```bash
pip install openai                                 # optional extra, not in CI
export OPENAI_BASE_URL=https://ai-gateway.uni-paderborn.de/v1/
export SYSMLCAD_OPENAI_MODEL=gwdg.qwen3.5-397b-a17b        # no default, on purpose
export SYSMLCAD_OPENAI_API_KEY_FILE=/workspaces/conf/upb_ai_api_key.txt
make propose-score AI=openai                       # how does it do?
```

That covers OpenAI, Azure, vLLM, LM Studio, Groq, OpenRouter, together.ai and
Ollama. The SDKs are optional extras: CI installs them only to test the AI
path against recorded responses, never with a key. A weaker model does not
become dangerous here, only less useful: its
answer is checked field by field against the catalogue, then gated, then shown
to a human. What changes with model quality is the scoreboard, not the safety
properties — which is exactly what `make propose-score AI=openai` measures.

**Is it any good?** `make propose-score PROJECT=gearbox` answers that against
the project's own `gold_mapping.yaml` — eleven attributes, two of which have
*no* correct mapping, so silence is the right answer:

```
project      : gearbox
proposer                    hit@1      hit@3   wrong@1   missed
baseline:difflib      11/11 (100%) 11/11 (100%)         0        0
```

Watch `wrong@1`, not the hit rate: a confident wrong answer costs more than a
missing one, because it looks exactly like a right one.

Three real models have been measured through this — against the **former
merged gold set** of thirteen attributes across both projects, before each
model got its own. The numbers are kept because the finding is what matters,
and they are not directly comparable to the per-project baseline above:

```
baseline:difflib (then)   11/13 (85%)   wrong@1 2   missed 0
gwdg.gemma-4-31b-it        4/13 (31%)   wrong@1 1   missed 8
gwdg.qwen3.5-397b-a17b     3/13 (23%)   wrong@1 5   missed 5
gemini-3.8-flash           4/13 (31%)   wrong@1 0   missed 9
```

Part of every model's difficulty was the merged set itself: two unrelated
`Housing`s in one excerpt, with nothing saying they came from different models.
That is gone — a project's excerpt now contains one model — so re-measuring
the models is the obvious next run.

Model size predicted nothing. The largest is worst, and worst in the column that
costs the most: it proposes the whole `gearbox` assembly for the housing's
length, width and height — and since the assembly's X extent equals the
housing's, that is a plausible number from the wrong object, which is the
failure this project exists to prevent.

Gemini 3.8 Flash failed the other way: two candidates for thirteen attributes,
both correct, nothing invented. Perfect precision, poor recall. By `wrong@1` it
is the best model tested; by usefulness it barely dents the work. Which of those
two failure modes you prefer is a real decision, and the scoreboard is what lets
you make it deliberately.

More telling still is what happened in a live `make propose` run with Gemma:
every one of its five candidates was rejected by a gate, four for proposing a
*volume* where the model asks for a length:

```
0 candidate(s) past the gates, 5 rejected by them, 0 new to the store
  housing.width -> gearbox via volume: volume yields [length] ** 3,
                   but width : LengthValue is [length]
```

That is the whole design in one line of output. A weak model is useless here,
not dangerous — and the scoreboard is how you tell which model you have.

One honest caveat: the baseline was tuned *after* seeing this gold set, so its
85% is a training score.

## Next steps

Re-measure the three language models per project: the numbers above predate
projects, and the merged excerpt was part of every model's difficulty. The
prompt has changed since as well — it no longer mentions supplying a density,
which the verification now refuses.

Then stage B: change-impact analysis — given a change on either side, derive the
affected requirements and verification cases from the model links instead of
estimating them, and report the link path that produced each one. It needs no
CAD write access and no new infrastructure.

Then C (evidence log and reports), D (MCP server), F (FreeCAD adapter) and
G (ownership-gated writes). Order that must not be broken: **gates before
writes, gates before AI, adapter seam before FreeCAD** — the middle one is now
satisfied rather than merely planned. Details and rationale in
[ROADMAP.md](ROADMAP.md).
