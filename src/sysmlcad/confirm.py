"""Human confirmation: the step that turns a proposal into a rule.

SRS FREQ-5 in one command. A proposal is reviewed, gated once more, and then --
only then -- written into `mapping.yaml` with the name of the person who
confirmed it and the time they did. After that it is an ordinary deterministic
entry; that it came from an AI no longer influences anything.

    python -m sysmlcad.confirm p-01
    python -m sysmlcad.confirm p-02 --reject --reason "wrong bore, that is the cover"

HOW IT WRITES
-------------
By appending text, not by re-serialising the file. `mapping.yaml` is half
commentary explaining why each entry exists, and every YAML round-tripper --
ruamel included -- reformats something on the way out: list indentation,
`null` versus empty, where a long quoted string wraps. Measured, not assumed:
a ruamel round-trip of today's mapping.yaml rewrites 38 lines it was asked to
leave alone.

So the new entry is rendered as text and inserted at the end of its section,
and every existing byte stays where it was. The safety net is that the result
is parsed back with `load_mapping()` before it is kept: if the file no longer
loads, or does not now contain exactly the intended entry, the original text
is put back and nothing is written.
"""

from __future__ import annotations

import argparse
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .catalog import load_catalog
from .extract import from_capture
from .project import Project, UnknownProject, add_project_argument, load_project
from .gates import check_entry
from .mapping import load_mapping
from .verify import AdapterPool, _leaf
from .proposals import (
    Proposal,
    decide,
    find,
    load_proposals,
    merged_mapping,
    save_proposals,
)


def current_user() -> str:
    """Whoever git thinks is working here. FREQ-5 wants a name on the record,
    and asking for one that is already configured is friction for its own sake."""
    try:
        name = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    return name or "unknown"


# --------------------------------------------------------------------------
# Writing into mapping.yaml
# --------------------------------------------------------------------------

def render_entry(fields: dict, indent: str = "  ") -> str:
    """One YAML list item, rendered from a dict.

    PyYAML does the quoting and escaping -- this is new text, so its layout is
    ours to choose, and only its correctness matters.
    """
    body = yaml.safe_dump(
        fields, sort_keys=False, allow_unicode=True, default_flow_style=False, width=88
    ).rstrip("\n").split("\n")
    lines = [f"{indent}- {body[0]}"]
    lines += [f"{indent}  {line}" for line in body[1:]]
    return "\n".join(lines) + "\n"


def insert_into_section(text: str, section: str, block: str) -> str:
    """Put `block` at the end of `section`'s list, touching nothing else.

    "The end of the section" is the last line that carries content, so a trailing
    blank line or a comment introducing the *next* section stays where its author
    put it.
    """
    lines = text.splitlines(keepends=True)

    start = next(
        (i for i, line in enumerate(lines) if line.rstrip("\n") == f"{section}:"),
        None,
    )
    if start is None:
        raise ValueError(f"{section}: no such section in the mapping")

    last = start
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if lines[i][:1] not in (" ", "\t", "\n", "") and not stripped.startswith("#"):
            break                      # the next top-level key
        if stripped and not stripped.startswith("#"):
            last = i

    return "".join(lines[: last + 1]) + block + "".join(lines[last + 1 :])


def write_entries(
    proposal: Proposal,
    user: str,
    path: Path,
) -> list[str]:
    """Append what this proposal becomes. Returns a note per section written."""
    original = path.read_text(encoding="utf-8")
    before = load_mapping(path)
    text = original
    written: list[str] = []

    if proposal.sysml_part not in before.parts:
        text = insert_into_section(text, "parts", "\n" + render_entry({
            "sysml_part": proposal.sysml_part,
            "adapter": proposal.adapter,
            "cad_object": proposal.cad_object,
            "status": "confirmed",
            "author": user,
            "confirmed_at": _today(),
            "note": f"{proposal.id}: {proposal.rationale}".strip(": "),
        }))
        written.append(f"parts: {proposal.sysml_part} -> {proposal.cad_object}")

    text = insert_into_section(text, "attributes", "\n" + render_entry({
        "sysml_part": proposal.sysml_part,
        "attribute": proposal.attribute,
        "requirement": proposal.requirement,
        "method": proposal.method,
        "args": dict(proposal.args),
        "direction": proposal.direction,
        "tolerance": None,
        "status": "confirmed",
        "author": user,
        "confirmed_at": _today(),
        "note": f"{proposal.id}, proposed by {proposal.proposed_by} "
                f"(confidence {proposal.confidence:.2f}): {proposal.rationale}",
    }))
    written.append(f"attributes: {proposal.sysml_part}.{proposal.attribute}")

    path.write_text(text, encoding="utf-8")

    # The safety net: it has to load, and it has to say what we meant.
    try:
        after = load_mapping(path)
        entry = next(
            e for e in after.attributes
            if (e.sysml_part, e.attribute) == (proposal.sysml_part, proposal.attribute)
            and e.method == proposal.method
        )
        assert entry.status == "confirmed"
        assert len(after.attributes) == len(before.attributes) + 1
    except Exception as exc:
        path.write_text(original, encoding="utf-8")
        raise RuntimeError(
            f"writing {proposal.id} into {path.name} produced a file that does "
            f"not read back as intended ({exc}). The original has been restored."
        ) from exc

    return written


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------

def confirm(
    project: Project,
    proposal_id: str,
    user: str = "",
    path: Path | None = None,
    proposals_path: Path | None = None,
) -> int:
    """`path` and `proposals_path` default to the project's own; tests pass
    temporary copies so the committed files are never touched."""
    path = path or project.mapping_path
    proposals_path = proposals_path or project.proposals_path
    proposals = load_proposals(proposals_path)
    proposal = find(proposals, proposal_id)
    if proposal is None:
        print(f"no proposal {proposal_id!r}. `python -m sysmlcad.propose --list` shows them.")
        return 2
    if not proposal.pending:
        print(f"{proposal_id} is already {proposal.status} "
              f"(by {proposal.decided_by or 'someone'} at {proposal.decided_at or '?'}).")
        return 2

    # Gate it once more, in the company it would keep. The mapping on disk may
    # have moved since the proposal was made, and a duplicate only shows up
    # against the entries that are actually there now.
    merged = merged_mapping(load_mapping(path), proposal)
    pool = AdapterPool()
    check = check_entry(
        merged.attributes[-1],
        merged,
        load_catalog(project, pool=pool),
        {(r.requirement_id, _leaf(r.subject)): r for r in from_capture(project)},
        pool,
    )

    print(f"\n{proposal.id}  {proposal.sysml_part}.{proposal.attribute}"
          f"  ->  {proposal.adapter}:{proposal.cad_object}"
          f"  via {proposal.method}({proposal.args or {}})")
    print(f"proposed by {proposal.proposed_by or 'unknown'} "
          f"with confidence {proposal.confidence:.2f}")
    if proposal.rationale:
        print(f"rationale   : {proposal.rationale}")
    for result in check.results:
        print(f"  {result.gate:<13} {result.verdict:<8} {result.detail}")

    if check.verdict == "invalid":
        print("\nNot confirmed: a gate says this mapping is wrong, and confirming "
              "it would make a wrong rule deterministic.\n")
        return 1

    user = user or current_user()
    written = write_entries(proposal, user, path)
    save_proposals(decide(proposals, proposal_id, "confirmed", user), proposals_path)

    print(f"\nconfirmed by {user}:")
    for note in written:
        print(f"  + {note}")
    print(f"\n{path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path} "
          f"now carries the entry. `make verify PROJECT={project.name}` will use it.\n")
    return 0


def reject(
    project: Project,
    proposal_id: str,
    reason: str,
    user: str = "",
    proposals_path: Path | None = None,
) -> int:
    proposals_path = proposals_path or project.proposals_path
    proposals = load_proposals(proposals_path)
    proposal = find(proposals, proposal_id)
    if proposal is None:
        print(f"no proposal {proposal_id!r}.")
        return 2

    user = user or current_user()
    save_proposals(decide(proposals, proposal_id, "rejected", user, reason), proposals_path)
    print(f"{proposal_id} rejected by {user}"
          f"{': ' + reason if reason else ''} -- kept in {proposals_path.name} as a record.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sysmlcad.confirm",
        description="Confirm or reject a mapping proposal (SRS FREQ-5).",
    )
    add_project_argument(parser)
    parser.add_argument("id", help="proposal id, e.g. p-01")
    parser.add_argument("--user", default="", help="who is deciding (default: git user.name)")
    parser.add_argument("--reject", action="store_true", help="record a rejection instead")
    parser.add_argument("--reason", default="", help="why it was rejected")
    args = parser.parse_args(argv)

    try:
        project = load_project(args.project)
    except UnknownProject as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.reject:
        return reject(project, args.id, args.reason, args.user)
    return confirm(project, args.id, args.user)


if __name__ == "__main__":
    raise SystemExit(main())
