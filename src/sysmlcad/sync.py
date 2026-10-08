"""Write SysML's requirement limits into the CAD documents -- and nothing else.

    python -m sysmlcad.sync --project cube_freecad            # dry run: the diff
    python -m sysmlcad.sync --project cube_freecad --apply    # write it

ROADMAP stage G, the downward direction, narrowed on purpose. The authority
rule is what keeps two models from colliding: SysML owns limits, CAD owns
actual values. So this writes exactly one kind of thing -- the limit of each
requirement whose part is mapped to a writable document -- into one place, a
spreadsheet the sync owns (`Project.limits_sheet`, default `SysML`). A designer
can reference it (`=SysML.MaxLength`); the sync never does that for them.

WHAT IT NEVER DOES
------------------
* write a value that drives geometry. An attribute entry with
  `direction: sysml_owns` says SysML owns the *value* -- writing it would
  rebuild a part without a human deciding to, which is exactly what the
  roadmap rules out. Such entries are reported, not written.
* write into a sheet it does not own. The worker refuses a sheet without the
  sync's marker, so a designer's `Params` sheet cannot be overwritten by a
  name clash.
* write without being asked: the default is the dry run.

Every applied change is appended to `out/sync_log.jsonl` with the model states
it came from and the document digest before and after -- the first lines of
the evidence log stage C will turn into a database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .adapters import LimitChange, Unsupported, WritableAdapter
from .extract import load_with_context
from .mapping import Mapping, load_mapping
from .project import Project, UnknownProject, add_project_argument, load_project
from .units import Q
from .verify import AdapterPool, _leaf

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "out" / "sync_log.jsonl"

#: What a FreeCAD spreadsheet accepts as an alias, and therefore what an
#: expression can refer to.
_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Planned:
    """One limit bound for one document."""

    adapter: str
    document: str
    alias: str
    limit: Q
    requirement: str
    subject: str


@dataclass
class Plan:
    writes: list[Planned] = field(default_factory=list)
    #: (requirement, reason) for every requirement that is not written.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    #: Entries whose VALUE SysML owns -- reported, never written.
    held_back: list[str] = field(default_factory=list)

    def documents(self) -> dict[tuple[str, str], dict[str, Planned]]:
        out: dict[tuple[str, str], dict[str, Planned]] = {}
        for write in self.writes:
            out.setdefault((write.adapter, write.document), {})[write.alias] = write
        return out


def plan(requirements, mapping: Mapping, pool: AdapterPool) -> Plan:
    """Which limit goes into which document, under which alias.

    Only confirmed entries on confirmed parts count -- the same rule a run
    applies, so a limit appears in a document exactly when the run would check
    that requirement against it.
    """
    result = Plan()
    # A requirement satisfied by two parts is two limits; the alias says which.
    repeated = Counter(r.requirement_id for r in requirements)

    for req in sorted(requirements, key=lambda r: (r.requirement_id, r.subject)):
        subject = _leaf(req.subject)
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
        if not isinstance(adapter, WritableAdapter):
            continue        # a STEP file or a script has nowhere to put a limit

        if entry.direction == "sysml_owns":
            result.held_back.append(
                f"{subject}.{entry.attribute}: direction sysml_owns -- SysML owns the "
                f"value, and writing it would change the geometry; only the limit "
                f"{req.requirement_id} is written"
            )

        alias = req.requirement_id if repeated[req.requirement_id] == 1 \
            else f"{req.requirement_id}_{subject}"
        if not _ALIAS.fullmatch(alias):
            result.skipped.append((
                req.requirement_id,
                f"{alias!r} is not a valid spreadsheet alias (letters, digits, _)",
            ))
            continue

        result.writes.append(Planned(
            adapter=part.adapter,
            document=part.cad_object.split("#", 1)[0],
            alias=alias,
            limit=req.limit,
            requirement=req.requirement_id,
            subject=subject,
        ))
    return result


def _fmt(quantity: Q) -> str:
    """Same format as the verification report, so a limit reads the same in both."""
    return f"{quantity:.4g~P}"


def _digest(document: str, root: Path) -> str:
    path = Path(document)
    path = path if path.is_absolute() else root / path
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else ""


def sync(project: Project, apply: bool = False, source: str | None = None,
         pool: AdapterPool | None = None, log: Path = LOG, root: Path = ROOT) -> int:
    requirements, _skipped, state = load_with_context(project, source)
    mapping = load_mapping(project.mapping_path)
    pool = pool or AdapterPool()
    planned = plan(requirements, mapping, pool)

    print(f"\nproject      : {project.name}")
    print(f"mapping      : {mapping.digest}")
    if state.get("sysml_commit_id"):
        print(f"sysml commit : {state['sysml_commit_id']}")
    print(f"sheet        : {project.limits_sheet}")
    print(f"mode         : {'APPLY' if apply else 'dry run -- nothing is written'}\n")

    failures = 0
    total = 0
    for (adapter_name, document), writes in sorted(planned.documents().items()):
        adapter = pool.get(adapter_name)
        values = {alias: w.limit for alias, w in writes.items()}
        before = _digest(document, root)
        try:
            changes = adapter.write_limits(document, project.limits_sheet, values, apply=apply)
        except Unsupported as exc:
            failures += 1
            print(f"{document}\n  NOT WRITTEN: {exc}\n")
            continue

        print(f"{document}  ({len(values)} limit(s), {len(changes)} change(s))")
        for change in changes:
            old = _fmt(change.old) if change.old is not None else "(new)"
            print(f"  {project.limits_sheet}.{change.alias:<24} {old:>14} -> {_fmt(change.new)}")
        print()
        total += len(changes)

        if apply and changes:
            _append_log(log, project, mapping, state, document, before,
                        _digest(document, root), changes)

    for requirement, reason in planned.skipped:
        print(f"  SKIPPED {requirement}: {reason}")
    for note in planned.held_back:
        print(f"  HELD BACK {note}")
    if not planned.writes and not planned.skipped:
        print("nothing to write: no confirmed entry maps a requirement onto a "
              "writable document")

    verb = "written" if apply else "would be written"
    print(f"\n{total} change(s) {verb}, {failures} document(s) failed"
          + ("" if apply or not total else "  -- run with --apply to write them"))
    return 1 if failures else 0


def _append_log(log: Path, project: Project, mapping: Mapping, state: dict,
                document: str, before: str, after: str,
                changes: list[LimitChange]) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": project.name,
        "sysml_commit_id": state.get("sysml_commit_id", ""),
        "mapping_digest": mapping.digest,
        "document": document,
        "sheet": project.limits_sheet,
        "digest_before": before,
        "digest_after": after,
        "changes": [
            {"alias": c.alias,
             "old": None if c.old is None else _fmt(c.old),
             "new": _fmt(c.new)}
            for c in changes
        ],
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.sync",
        description="Write SysML requirement limits into the project's CAD documents.",
    )
    add_project_argument(parser)
    parser.add_argument("source", nargs="?", default=None,
                        help="'api' for the live server; omit for the project's capture")
    parser.add_argument("--apply", action="store_true",
                        help="write the changes; without it this is a dry run")
    args = parser.parse_args(argv)
    try:
        project = load_project(args.project)
    except UnknownProject as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return sync(project, apply=args.apply, source=args.source)


if __name__ == "__main__":
    raise SystemExit(main())
