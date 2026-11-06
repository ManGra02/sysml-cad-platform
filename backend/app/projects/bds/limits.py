"""Write SysML's requirement limits into the FreeCAD documents -- and nothing else.

The downward direction, narrowed on purpose. SysML owns limits, CAD owns actual
values; so this writes exactly one kind of thing -- the limit of each requirement
whose part is mapped -- into one place, a spreadsheet the sync owns (default
``SysML``). A designer can reference it (``=SysML.MaxLength``); the sync never does
that for them.

It never writes a value that drives geometry (entries with ``direction: sysml_owns``
are reported, not written), never writes into a sheet it does not own (the marker in
A1, see freecad_limits), and never writes without being asked: the default is the
dry run.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from app.projects.bds.adapters import Unsupported
from app.projects.bds.extract import leaf
from app.projects.bds.model import now
from app.projects.bds.units import as_json, fmt

#: What a FreeCAD spreadsheet accepts as an alias.
_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Planned:
    adapter: str
    document: str
    alias: str
    limit: object
    requirement: str
    subject: str


@dataclass
class Plan:
    writes: list = field(default_factory=list)
    skipped: list = field(default_factory=list)          # (requirement, reason)
    held_back: list = field(default_factory=list)

    def documents(self):
        out = {}
        for write in self.writes:
            out.setdefault((write.adapter, write.document), {})[write.alias] = write
        return out


def plan(requirements, mapping, pool):
    """Which limit goes into which document, under which alias. Only confirmed entries
    on confirmed parts -- a limit appears in a document exactly when a run would check
    that requirement against it."""
    result = Plan()
    repeated = Counter(r.requirement_id for r in requirements)

    for req in sorted(requirements, key=lambda r: (r.requirement_id, r.subject)):
        subject = leaf(req.subject)
        entry = mapping.for_requirement(req.requirement_id, subject)
        if entry is None or not entry.usable:
            continue
        part = mapping.part_for(entry)
        if part is None or not part.usable:
            continue
        try:
            adapter = pool.get(part.adapter)
        except Unsupported as exc:
            result.skipped.append((req.requirement_id, str(exc)))
            continue
        if not hasattr(adapter, "write_limits"):
            continue

        if entry.direction == "sysml_owns":
            result.held_back.append(
                "%s.%s: direction sysml_owns -- SysML owns the value, and writing it would change the "
                "geometry; only the limit %s is written" % (subject, entry.attribute, req.requirement_id))

        # A requirement satisfied by two parts is two limits; the alias says which.
        alias = req.requirement_id if repeated[req.requirement_id] == 1 else "%s_%s" % (req.requirement_id, subject)
        if not _ALIAS.fullmatch(alias):
            result.skipped.append((req.requirement_id,
                                   "%r is not a valid spreadsheet alias (letters, digits, _)" % alias))
            continue
        result.writes.append(Planned(adapter=part.adapter, document=part.cad_object.split("#", 1)[0],
                                     alias=alias, limit=req.limit, requirement=req.requirement_id,
                                     subject=subject))
    return result


async def sync(workspace, requirements, mapping, pool, state, apply=False):
    """Dry run (default) or apply -> {documents[], skipped[], held_back[], changes, failures}."""
    planned = plan(requirements, mapping, pool)
    documents = []
    total = failures = 0

    for (adapter_name, document), writes in sorted(planned.documents().items()):
        adapter = pool.get(adapter_name)
        values = {alias: w.limit for alias, w in writes.items()}
        try:
            changes = await adapter.write_limits(document, workspace.limits_sheet, values, apply=apply)
        except Unsupported as exc:
            failures += 1
            documents.append({"document": document, "error": str(exc), "changes": []})
            continue
        total += len(changes)
        documents.append({
            "document": document,
            "limits": {alias: as_json(q) for alias, q in sorted(values.items())},
            "changes": [{"alias": c.alias, "old": as_json(c.old), "new": as_json(c.new)} for c in changes],
        })
        if apply and changes:
            _append_log(workspace, mapping, state, document, changes)

    return {
        "apply": apply,
        "sheet": workspace.limits_sheet,
        "mapping_digest": mapping.digest,
        "sysml_commit_id": state.get("sysml_commit_id", ""),
        "documents": documents,
        "skipped": [{"requirement": r, "reason": reason} for r, reason in planned.skipped],
        "held_back": planned.held_back,
        "changes": total,
        "failures": failures,
    }


def _append_log(workspace, mapping, state, document, changes):
    record = {
        "at": now(),
        "workspace": workspace.name,
        "sysml_commit_id": state.get("sysml_commit_id", ""),
        "mapping_digest": mapping.digest,
        "document": document,
        "sheet": workspace.limits_sheet,
        "changes": [{"alias": c.alias, "old": fmt(c.old), "new": fmt(c.new)} for c in changes],
    }
    workspace.root.mkdir(parents=True, exist_ok=True)
    with workspace.sync_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
