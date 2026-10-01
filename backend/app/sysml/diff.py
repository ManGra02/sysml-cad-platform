"""Client-side diff of two snapshots (Flexo's /diff endpoint is not implemented yet).

Used for change detection: which parts appeared (need a CAD mapping), which attribute
values changed (re-run verification / impact analysis)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import ModelSnapshot


def diff_snapshots(base: ModelSnapshot, compare: ModelSnapshot) -> dict[str, Any]:
    b_el = {e.id: e for e in base.elements}
    c_el = {e.id: e for e in compare.elements}
    added = [asdict(c_el[i]) for i in c_el.keys() - b_el.keys()]
    removed = [asdict(b_el[i]) for i in b_el.keys() - c_el.keys()]
    changed = []
    for i in b_el.keys() & c_el.keys():
        a, b = b_el[i], c_el[i]
        fields = {f: (getattr(a, f), getattr(b, f)) for f in ("name", "parent_id", "type_ids", "native_type", "doc")
                  if getattr(a, f) != getattr(b, f)}
        if fields:
            changed.append({"id": i, "name": b.name, "changes": {k: {"from": v[0], "to": v[1]} for k, v in fields.items()}})

    b_at = {a.id: a for a in base.attributes}
    c_at = {a.id: a for a in compare.attributes}
    attr_changed = []
    for i in b_at.keys() & c_at.keys():
        a, b = b_at[i], c_at[i]
        if (a.value, a.unit) != (b.value, b.unit):
            owner = c_el.get(b.owner_id)
            attr_changed.append({"id": i, "owner_id": b.owner_id, "owner": owner.name if owner else None,
                                 "name": b.name, "from": a.expression, "to": b.expression,
                                 "from_si": a.value_si, "to_si": b.value_si, "unit_si": b.unit_si})
    return {
        "base": base.version, "compare": compare.version,
        "elements": {"added": added, "removed": removed, "changed": changed},
        "attributes": {
            "added": [asdict(c_at[i]) for i in c_at.keys() - b_at.keys()],
            "removed": [asdict(b_at[i]) for i in b_at.keys() - c_at.keys()],
            "changed": attr_changed,
        },
        "summary": {
            "elements_added": len(added), "elements_removed": len(removed), "elements_changed": len(changed),
            "attributes_changed": len(attr_changed),
            "parts_added": [e["name"] for e in added if e["kind"] == "part"],
        },
    }
