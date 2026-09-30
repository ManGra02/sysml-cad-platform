"""Command line for the SysML adapter -- setup, test data, a quick look at a model.

    cd backend
    uv run python -m app.sysml status
    uv run python -m app.sysml setup-org             # once per fresh Flexo database
    uv run python -m app.sysml seed-demo             # e-bike demo  (--model parts-tree)
    uv run python -m app.sysml tree "EBike Demo"
    uv run python -m app.sysml --help

Talks to SYSML_API_URL (default http://127.0.0.1:8083), see app/sysml/config.py.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.sysml.client import SysmlError, create_sysmlv2_org
from app.sysml.config import FLEXO_DIR, SysmlConfig, read_env_file
from app.sysml.demo import load_sample
from app.sysml.parser import parse_elements
from app.sysml.service import SysmlService


def _table(rows, headers):
    rows = [["" if c is None else str(c) for c in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))


def _json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False,
                     default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o)))


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m app.sysml", description="SysML v2 adapter (Flexo MMS)")
    ap.add_argument("--url", help="SysML v2 API base URL (default: $SYSML_API_URL or http://127.0.0.1:8083)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="is the SysML v2 API reachable?")
    s = sub.add_parser("setup-org", help="once per fresh Flexo database: create the 'sysmlv2' org")
    s.add_argument("--env-file", default=str(FLEXO_DIR / "env" / "flexo-sysmlv2.env"),
                   help="env file with FLEXO_AUTH (default: flexo/env/flexo-sysmlv2.env)")
    sub.add_parser("projects", help="list projects")
    s = sub.add_parser("create-project")
    s.add_argument("name")
    s.add_argument("--description", default="")
    s = sub.add_parser("seed-demo", help="create a project and commit a demo model")
    s.add_argument("--model", choices=["ebike", "parts-tree"], default="ebike")
    s.add_argument("--name", help="project name (default depends on the model)")
    s = sub.add_parser("load-file", help="commit a JSON file (commit payload or element list) into a project")
    s.add_argument("project")
    s.add_argument("file")
    s.add_argument("--message", default="Loaded from file")

    def versioned(p):
        p.add_argument("project", help="project id or name")
        p.add_argument("--branch")
        p.add_argument("--commit")
        return p

    sub.add_parser("commits", help="list commits").add_argument("project")
    versioned(sub.add_parser("tree", help="part tree with attribute values"))
    versioned(sub.add_parser("parts", help="part usages")).add_argument("--leaf-only", action="store_true")
    versioned(sub.add_parser("attributes", help="attributes with value and SI value")).add_argument("--element")
    versioned(sub.add_parser("requirements", help="requirements and who satisfies them"))
    s = versioned(sub.add_parser("snapshot", help="common-model snapshot as JSON"))
    s.add_argument("--out")
    versioned(sub.add_parser("dump-raw", help="raw Flexo JSON of a commit")).add_argument("--out", required=True)
    s = sub.add_parser("set-value", help="new value for an attribute (creates a commit)")
    s.add_argument("project")
    s.add_argument("attribute_id")
    s.add_argument("value", type=float)
    s.add_argument("--unit")
    s.add_argument("--branch")
    s.add_argument("--message")
    s = sub.add_parser("diff", help="compare two commits")
    s.add_argument("project")
    s.add_argument("base")
    s.add_argument("compare")
    s = sub.add_parser("parse-file", help="OFFLINE: parse a raw JSON file and print the tree")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    return ap


async def run(a, config):
    if a.cmd == "parse-file":
        snap = parse_elements(json.loads(Path(a.file).read_text(encoding="utf-8")), version=Path(a.file).name)
        print(snap.to_json() if a.json else snap.tree_text() + "\n\nstats: %s" % snap.stats())
        return 0
    if a.cmd == "setup-org":
        token = read_env_file(a.env_file).get("FLEXO_AUTH")
        if not token:
            print("No FLEXO_AUTH in %s" % a.env_file, file=sys.stderr)
            return 1
        await create_sysmlv2_org(config, token)
        print("org %r created on %s" % (config.org, config.layer1_url))
        return 0

    service = SysmlService(config)
    client = service.client
    try:
        if a.cmd == "status":
            st = await service.status()
            print("%s: %s" % (st["url"], "reachable, %d project(s)" % st["projects"] if st["reachable"]
                              else "NOT reachable (%s)" % st["message"]))
            return 0 if st["reachable"] else 2
        if a.cmd == "projects":
            _table([[p["id"], p["name"], p["defaultBranch"], p["created"]] for p in await service.projects()],
                   ["id", "name", "default branch", "created"])
            return 0
        if a.cmd == "create-project":
            p = await client.create_project(a.name, a.description)
            print("created project %s  (%s)" % (p.get("@id"), a.name))
            return 0
        if a.cmd in ("seed-demo", "load-file"):
            if a.cmd == "seed-demo":
                name = a.name or ("EBike Demo" if a.model == "ebike" else "Parts Tree Demo")
                p = await client.create_project(name, "demo model %r created by app.sysml" % a.model)
                pid, payload, message = p["@id"], load_sample(a.model), "seed %s" % a.model
                print("created project %s  (%s)" % (pid, name))
            else:
                pid = await service.resolve_project_id(a.project)
                payload, message = json.loads(Path(a.file).read_text(encoding="utf-8")), a.message
            changes = payload["change"] if isinstance(payload, dict) and "change" in payload else \
                [{"identity": {"@id": e.get("@id")}, "payload": e} for e in payload]
            commit = await client.post_commit(pid, changes, description=message)
            print("committed %d elements -> commit %s" % (len(changes), commit.get("@id")))
            return 0
        if a.cmd == "commits":
            _table([[c["id"], c["created"], c["description"]] for c in await service.commits(a.project)],
                   ["id", "created", "description"])
            return 0
        if a.cmd == "set-value":
            commit = await service.write_attribute_value(a.project, a.attribute_id, a.value, unit=a.unit,
                                                         branch_id=a.branch, description=a.message)
            print("new commit %s" % commit.get("@id"))
            return 0
        if a.cmd == "diff":
            _json(await service.diff(a.project, a.base, a.compare))
            return 0

        version = {"branch_id": a.branch, "commit_id": a.commit}
        if a.cmd == "dump-raw":
            raw = await service.raw_elements(a.project, **version)
            Path(a.out).write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
            print("wrote %d elements to %s" % (len(raw), a.out))
            return 0
        snap = await service.snapshot(a.project, **version)
        name = lambda i: snap.element(i).name if i and snap.element(i) else ""  # noqa: E731
        if a.cmd == "tree":
            print("# project %s @ commit %s\n\n%s" % (snap.project_id, snap.version, snap.tree_text()))
        elif a.cmd == "parts":
            items = snap.leaf_parts() if a.leaf_only else snap.parts()
            _table([[p.id, p.name, name(p.parent_id), ", ".join(name(t) for t in p.type_ids)] for p in items],
                   ["id", "name", "parent", "typed by"])
        elif a.cmd == "attributes":
            items = snap.attributes_of(a.element) if a.element else snap.attributes
            _table([[x.id, "%s.%s" % (name(x.owner_id), x.name), x.expression, x.value_si, x.unit_si]
                    for x in items], ["id", "attribute", "value", "value (SI)", "SI unit"])
        elif a.cmd == "requirements":
            satisfied = {}
            for r in snap.relations:
                if r.kind == "satisfies":
                    satisfied.setdefault(r.target_id, []).append(name(r.source_id))
            _table([[r.id, r.extra.get("req_id"), r.name, r.extra.get("text"), ", ".join(satisfied.get(r.id, []))]
                    for r in snap.requirements()], ["id", "req id", "name", "text", "satisfied by"])
        elif a.cmd == "snapshot":
            if a.out:
                Path(a.out).write_text(snap.to_json(), encoding="utf-8")
                print("wrote %s  commit=%s  %s" % (a.out, snap.version, snap.stats()))
            else:
                print(snap.to_json())
        return 0
    finally:
        await service.stop()


def main(argv=None):
    a = build_parser().parse_args(argv)
    config = SysmlConfig.from_env()
    if a.url:
        config.api_url = a.url.rstrip("/")
    try:
        return asyncio.run(run(a, config))
    except SysmlError as exc:
        print("SysML error [%s]: %s" % (exc.code, exc.message), file=sys.stderr)
        if exc.code == "sysml_unreachable":
            print("-> is Flexo running?  docker compose -f flexo/docker-compose.yml up -d", file=sys.stderr)
        elif exc.code == "sysml_upstream_error" and "orgs" in str(exc.detail):
            print("-> fresh database?  uv run python -m app.sysml setup-org", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
