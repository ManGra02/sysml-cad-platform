"""A throwaway tool for looking at the real API payloads.

Not production code. Its purpose is to see the shape of a
RequirementDefinition before writing extract._to_requirement against it.

    python -m sysmlcad.explore              # overview + dump to out/
    python -m sysmlcad.explore MaxLength    # tree of one requirement

For the CAD side of the same question, see explore_cad.py.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .sysml_client import SysMLClient

OUT = Path("out/elements.json")


def fetch_all(client: SysMLClient, project_id: str, commit_id: str) -> list[dict]:
    """Follows every page. The API returns 100 elements per page and links
    the next one in the Link header."""
    url = f"/projects/{project_id}/commits/{commit_id}/elements?page[size]=200"
    out: list[dict] = []
    while url:
        r = client._c.get(url)
        r.raise_for_status()
        out.extend(r.json())
        nxt = r.links.get("next")
        url = nxt["url"] if nxt else None
    return out


def index(elements: list[dict]) -> dict[str, dict]:
    return {e["@id"]: e for e in elements if "@id" in e}


def label(e: dict) -> str:
    name = e.get("declaredName") or e.get("name") or ""
    return f"{e.get('@type', '?')}{f' [{name}]' if name else ''}"


def walk(eid: str, by_id: dict[str, dict], depth: int = 0, seen: set | None = None) -> None:
    """Follows every @id reference of an element, recursively."""
    seen = seen if seen is not None else set()
    if eid in seen or depth > 8:
        return
    seen.add(eid)
    e = by_id.get(eid)
    if e is None:
        return
    print("  " * depth + label(e))

    # Print literals and operators inline -- that is where the limit sits.
    for key in ("value", "operator", "shortName"):
        if key in e and e[key] is not None:
            print("  " * (depth + 1) + f".{key} = {e[key]!r}")

    for key, val in e.items():
        if key.startswith("@") or key in ("owner", "owningNamespace", "owningRelationship"):
            continue
        refs = val if isinstance(val, list) else [val]
        for ref in refs:
            if isinstance(ref, dict) and set(ref) == {"@id"}:
                walk(ref["@id"], by_id, depth + 1, seen)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .project import UnknownProject, add_project_argument, load_project

    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.explore",
        description="Dump one project's elements from the live server.",
    )
    add_project_argument(parser)
    parser.add_argument("name", nargs="?", default=None,
                        help="an element name to print the tree of, e.g. MaxLength")
    args = parser.parse_args(argv)

    try:
        project = load_project(args.project)
    except UnknownProject as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    client = SysMLClient()
    try:
        projects = [p for p in client.projects() if p.get("name") == project.sysml_project]
        if not projects:
            print(f"No project named {project.sysml_project!r} on the server.")
            return 1
        # Same name published twice: the newest of those, and say so.
        proj = sorted(projects, key=lambda p: p.get("created", ""))[-1]
        print(f"Project: {proj.get('name')} ({proj['@id']})")

        commit = client.head_commit(proj["@id"])
        elements = fetch_all(client, proj["@id"], commit)
    finally:
        client.close()

    print(f"{len(elements)} elements\n")
    for typ, n in Counter(e.get("@type") for e in elements).most_common(15):
        print(f"  {n:4d}  {typ}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(elements, indent=2), encoding="utf-8")
    print(f"\nFull dump: {OUT}")

    by_id = index(elements)
    wanted = args.name
    if wanted:
        hits = [e for e in elements if (e.get("declaredName") or e.get("name")) == wanted]
        if not hits:
            print(f"\nNo element named {wanted!r}.")
            return 1
        for h in hits:
            print(f"\n=== tree of {label(h)} ===")
            walk(h["@id"], by_id)
    else:
        names = sorted(
            {e.get("declaredName") for e in elements if e.get("declaredName")}
        )
        print("\nNamed elements:", ", ".join(names[:30]))
        print(f"\nNext: python -m sysmlcad.explore --project {project.name} MaxLength")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
