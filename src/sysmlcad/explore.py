"""Einmal-Werkzeug fuer Phase 1: die echten Payloads sichtbar machen.

Kein Produktivcode. Zweck ist, die Struktur einer RequirementDefinition
zu sehen, bevor extract._to_requirement dagegen geschrieben wird.

    python -m sysmlcad.explore              # Uebersicht + Dump nach out/
    python -m sysmlcad.explore MaxLength    # Baum einer Anforderung
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .sysml_client import SysMLClient

OUT = Path("out/elements.json")


def fetch_all(client: SysMLClient, project_id: str, commit_id: str) -> list[dict]:
    """Blaettert durch alle Seiten. Die API liefert 100 Elemente pro Seite
    und verlinkt die naechste im Link-Header."""
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
    """Folgt allen @id-Referenzen eines Elements rekursiv."""
    seen = seen if seen is not None else set()
    if eid in seen or depth > 8:
        return
    seen.add(eid)
    e = by_id.get(eid)
    if e is None:
        return
    print("  " * depth + label(e))

    # Literale und Operatoren direkt mit ausgeben -- dort steckt der Grenzwert.
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


def main() -> int:
    client = SysMLClient()
    try:
        projects = client.projects()
        if not projects:
            print("Keine Projekte im Server.")
            return 1
        # Das zuletzt angelegte Projekt gewinnt.
        proj = sorted(projects, key=lambda p: p.get("created", ""))[-1]
        print(f"Projekt: {proj.get('name')} ({proj['@id']})")

        commit = client.head_commit(proj["@id"])
        elements = fetch_all(client, proj["@id"], commit)
    finally:
        client.close()

    print(f"{len(elements)} Elemente\n")
    for typ, n in Counter(e.get("@type") for e in elements).most_common(15):
        print(f"  {n:4d}  {typ}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(elements, indent=2), encoding="utf-8")
    print(f"\nVollstaendiger Dump: {OUT}")

    by_id = index(elements)
    wanted = sys.argv[1] if len(sys.argv) > 1 else None
    if wanted:
        hits = [e for e in elements if (e.get("declaredName") or e.get("name")) == wanted]
        if not hits:
            print(f"\nKein Element mit Namen {wanted!r}.")
            return 1
        for h in hits:
            print(f"\n=== Baum von {label(h)} ===")
            walk(h["@id"], by_id)
    else:
        names = sorted(
            {e.get("declaredName") for e in elements if e.get("declaredName")}
        )
        print("\nBenannte Elemente:", ", ".join(names[:30]))
        print("\nNaechster Schritt: python -m sysmlcad.explore MaxLength")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
