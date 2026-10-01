# Flexo MMS -- the SysML v2 repository

The backend reads and writes the SysML v2 model through the standard Systems Modeling
API. Locally that API is served by [Flexo MMS](https://github.com/Open-MBEE/flexo-mms-sysmlv2),
three containers started by this folder:

```
backend (app/sysml)  --HTTP-->  flexo-sysmlv2 :8083  -->  layer1 :8080  -->  Fuseki :3030
                                SysML v2 API              versioning        RDF triple store
```

Prerequisite: Docker Desktop (on Windows with WSL 2 and virtualization enabled in the BIOS).

```bash
docker compose -f flexo/docker-compose.yml up -d      # ~1 min on the first start (image download)
cd backend
uv run python -m app.sysml status                     # "reachable, 0 project(s)"
uv run python -m app.sysml setup-org                  # once per fresh database
uv run python -m app.sysml seed-demo                  # e-bike demo model -> a project + commit
uv run python -m app.sysml tree "EBike Demo"
```

Then the model is available in the running platform under `http://127.0.0.1:8000/api/sysml/...`
(see `/api/docs`) and to project modules as `self.ctx.sysml`.

**The database lives in memory.** `docker compose down` (or a reboot) empties it; run
`setup-org` and `seed-demo` again. `docker compose stop` keeps it.

**Without Docker:** `uv run python ../tests/backend/fake_flexo.py --port 8083` (from `backend/`)
serves the same API in memory -- enough for development, not a replacement for real Flexo.

## Why this differs from upstream's docker-compose

| Problem with upstream's file | Symptom | Change here |
| --- | --- | --- |
| `atomgraph/fuseki:4.6` ships a Java that crashes on cgroup v2 | `quad-server` exits at start (`CgroupV2Subsystem` NullPointerException); layer1 then answers `UnresolvedAddressException` | `atomgraph/fuseki:4.7`, as in upstream's own test setup |
| Fuseki reserves 8 GB heap (`env/flexo-mms-quad-store.env`) | reads take 3-6 s, creating a project hangs 13-37 min, then HTTP 500 | `-Xmx1g -Xms256m` |
| three JVMs share the Docker VM | same starvation in layer1 / sysmlv2 | `-Xmx768m` (layer1), `-Xmx384m` (sysmlv2) |
| ports bound to all interfaces | reachable from the network | `127.0.0.1:` only, like the rest of the platform |

Docker's memory on Windows is set in `%USERPROFILE%\.wslconfig`: `[wsl2]` / `memory=4GB`
(about half of the RAM). Check with `docker info` -> "Total Memory".

## Credentials

`env/flexo-sysmlv2.env` contains `FLEXO_AUTH`, the JWT the SysML v2 service uses towards
layer1, and `env/flexo-mms-jwt.env` the matching secret. Both are upstream's public
development defaults -- fine for a loopback-only setup, never for a shared server.
If the token has expired, generate one with the secret as in upstream's
`src/test/kotlin/.../util/Auth.kt`.
