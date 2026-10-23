"""Confirmation: the step that turns a proposal into a rule.

A proposal is gated once more -- in the company of the mapping as it is NOW -- and
only then written into mapping.yaml. After that it is an ordinary deterministic entry.

HOW IT WRITES: by inserting text, not by re-serialising the file. mapping.yaml is
half commentary, and every YAML round-tripper reformats something on the way out.
The new entry is rendered as text and inserted at the end of its section; every
existing byte stays where it was. The result is parsed back before it is kept: if it
no longer loads, or does not contain exactly the intended entry, the original text
is put back.

There is no user identity: the platform runs locally for one person. ``author``
records where the entry came from (the proposer), ``confirmed_at`` when.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import yaml

from app.projects.bds.gates import check_proposal
from app.projects.bds.mapping import EMPTY, load_mapping
from app.projects.bds.proposals import decide, find, load_proposals, save_proposals
from app.projects.bds.workspace import BdsError


def render_entry(fields, indent="  "):
    body = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True, default_flow_style=False,
                          width=88).rstrip("\n").split("\n")
    lines = ["%s- %s" % (indent, body[0])]
    lines += ["%s  %s" % (indent, line) for line in body[1:]]
    return "\n".join(lines) + "\n"


def insert_into_section(text, section, block):
    """Put ``block`` at the end of ``section``'s list, touching nothing else. A trailing
    blank line or a comment introducing the next section stays where it was."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.rstrip("\r\n") == "%s:" % section), None)
    if start is None:
        raise ValueError("%s: no such section in the mapping" % section)
    last = start
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if lines[i][:1] not in (" ", "\t", "\n", "\r", "") and not stripped.startswith("#"):
            break                      # the next top-level key
        if stripped and not stripped.startswith("#"):
            last = i
    return "".join(lines[: last + 1]) + block + "".join(lines[last + 1:])


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_entries(proposal, path):
    """Append what this proposal becomes -> a note per section written."""
    if not path.is_file():
        path.write_text(EMPTY, encoding="utf-8")
    original = path.read_text(encoding="utf-8")
    before = load_mapping(path)
    text = original
    written = []

    if proposal.sysml_part not in before.parts:
        text = insert_into_section(text, "parts", "\n" + render_entry({
            "sysml_part": proposal.sysml_part,
            "adapter": proposal.adapter,
            "cad_object": proposal.cad_object,
            "status": "confirmed",
            "author": proposal.proposed_by,
            "confirmed_at": _today(),
            "note": ("%s: %s" % (proposal.id, proposal.rationale)).strip(": "),
        }))
        written.append("parts: %s -> %s" % (proposal.sysml_part, proposal.cad_object))

    text = insert_into_section(text, "attributes", "\n" + render_entry({
        "sysml_part": proposal.sysml_part,
        "attribute": proposal.attribute,
        "requirement": proposal.requirement,
        "method": proposal.method,
        "args": dict(proposal.args),
        "direction": proposal.direction,
        "tolerance": None,
        "status": "confirmed",
        "author": proposal.proposed_by,
        "confirmed_at": _today(),
        "note": "%s, proposed by %s (confidence %.2f): %s" % (
            proposal.id, proposal.proposed_by, proposal.confidence, proposal.rationale),
    }))
    written.append("attributes: %s.%s" % (proposal.sysml_part, proposal.attribute))
    path.write_text(text, encoding="utf-8")

    # The safety net: it has to load, and it has to say what was meant.
    try:
        after = load_mapping(path)
        added = after.attributes[len(before.attributes):]
        if len(added) != 1 or after.attributes[: len(before.attributes)] != before.attributes:
            raise ValueError("expected exactly one new attribute entry at the end, found %d" % len(added))
        entry = added[0]
        if (entry.sysml_part, entry.attribute, entry.method, entry.status) != (
                proposal.sysml_part, proposal.attribute, proposal.method, "confirmed"):
            raise ValueError("the new entry reads back as %s" % (entry,))
        part = after.parts.get(proposal.sysml_part)
        if part is None or (part.adapter, part.cad_object) != (proposal.adapter, proposal.cad_object):
            raise ValueError("%s reads back as %s" % (
                proposal.sysml_part, "%s:%s" % (part.adapter, part.cad_object) if part else "unmapped"))
    except Exception as exc:
        path.write_text(original, encoding="utf-8")
        raise BdsError(500, "bds_mapping_write_failed",
                       "Writing %s into %s produced a file that does not read back as intended (%s). "
                       "The original has been restored." % (proposal.id, path.name, exc)) from exc
    return written


def _pending(proposals, proposal_id):
    proposal = find(proposals, proposal_id)
    if proposal is None:
        raise BdsError(404, "bds_proposal_not_found", "No proposal %r" % proposal_id)
    if not proposal.pending:
        # Rejecting a confirmed proposal would leave the record saying "no" while the
        # mapping still carries it; undoing a confirmation is an edit to mapping.yaml.
        raise BdsError(409, "bds_proposal_decided", "%s is already %s (at %s)"
                       % (proposal_id, proposal.status, proposal.decided_at or "?"))
    return proposal


def confirm(workspace, proposal_id, catalog, requirements, pool, requirement=None):
    """Gate once more, then write. -> {proposal, check, written, part_usable}.

    ``requirement`` links the entry to the requirement it is checked through. A
    proposer cannot know it (the extractor does not parse which attribute a constraint
    reads), and an entry without one is never used by a run -- so the human confirming
    says it, and it must be a requirement the model states for this part.
    """
    proposals = load_proposals(workspace.proposals_path)
    proposal = _pending(proposals, proposal_id)
    if requirement:
        if (requirement, proposal.sysml_part) not in requirements:
            raise BdsError(400, "bds_unknown_requirement",
                           "The model has no requirement %r on part %r" % (requirement, proposal.sysml_part),
                           {"requirements": sorted(r for r, part in requirements if part == proposal.sysml_part)})
        proposal = replace(proposal, requirement=requirement)
        proposals = [proposal if p.id == proposal_id else p for p in proposals]

    check = check_proposal(proposal, load_mapping(workspace.mapping_path), catalog, requirements, pool)
    if check.verdict == "invalid":
        raise BdsError(409, "bds_gate_failed",
                       "Not confirmed: a gate says this mapping is wrong, and confirming it would make "
                       "a wrong rule deterministic.", {"check": check.to_dict()})

    written = write_entries(proposal, workspace.mapping_path)
    proposals = decide(proposals, proposal_id, "confirmed")
    save_proposals(proposals, workspace.proposals_path)
    part = load_mapping(workspace.mapping_path).parts[proposal.sysml_part]
    return {
        "proposal": find(proposals, proposal_id).to_dict(),
        "check": check.to_dict(),
        "written": written,
        # The attribute is confirmed, but an existing part entry keeps its own status:
        # a run uses it only once that is confirmed too.
        "part_usable": part.usable,
    }


def reject(workspace, proposal_id, reason=""):
    proposals = load_proposals(workspace.proposals_path)
    _pending(proposals, proposal_id)
    proposals = decide(proposals, proposal_id, "rejected", reason)
    save_proposals(proposals, workspace.proposals_path)
    return find(proposals, proposal_id).to_dict()
