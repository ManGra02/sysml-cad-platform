"""Does a BDS example model survive the round trip through Flexo?

BDS reads requirements from the full SysML v2 metamodel. Flexo stores elements as RDF
and serialises them anew on every read; this checks that what comes back still yields
the same requirements and the same catalogue as the file that went in.

    cd backend && uv run python ../scripts/bds_flexo_check.py [gearbox|motor_housing|cube]

Needs a running Flexo (docker compose -f flexo/docker-compose.yml up -d, then
`uv run python -m app.sysml setup-org`). Creates one new project per run.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.projects.bds.catalog import sysml_catalog  # noqa: E402
from app.projects.bds.extract import extract  # noqa: E402
from app.sysml.config import SysmlConfig  # noqa: E402
from app.sysml.service import SysmlService  # noqa: E402

MODELS = REPO / "data" / "examples" / "sysml" / "bds"


def summary(elements):
    requirements, skipped = extract(elements)
    return {
        "requirements": sorted((r.requirement_id, r.subject, r.operator, format(r.limit, "~P"))
                               for r in requirements),
        "not_extracted": sorted(skipped),
        "parts": sorted((p.qualified, p.definition, p.container, tuple((a.name, a.type_name) for a in p.attributes))
                        for p in sysml_catalog(elements)),
    }


async def main(model):
    original = json.loads((MODELS / ("%s.json" % model)).read_text(encoding="utf-8"))
    service = SysmlService(SysmlConfig.from_env())
    try:
        name = "BDS check %s %d" % (model, time.time())
        project = await service.client.create_project(name, "round-trip check of %s.json" % model)
        changes = [{"identity": {"@id": e["@id"]}, "payload": e} for e in original]
        commit = await service.client.post_commit(project["@id"], changes, description="bds check")
        back = await service.raw_elements(project["@id"], commit_id=commit["@id"])
    finally:
        await service.stop()

    before, after = summary(original), summary(back)
    print("project %r: %d elements in, %d back" % (name, len(original), len(back)))
    ok = True
    for key in before:
        same = before[key] == after[key]
        ok &= same
        print("  %-14s %s" % (key, "same" if same else "DIFFERENT"))
        if not same:
            print("    file : %s" % (before[key],))
            print("    flexo: %s" % (after[key],))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "gearbox")))
