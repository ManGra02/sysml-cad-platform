"""Changing the mapping after the fact: choose a measurement by hand, relink a
requirement, change a tolerance, release an entry.

Same rule as confirm.py: mapping.yaml is half commentary, so it is never
re-serialised. Only the one entry concerned is rewritten (or removed) as text; every
other byte stays where it was, and the result is parsed back before it is kept --
if it does not say what was meant, the original is put back.

An attribute entry is named by (part, attribute, requirement): one attribute may be
checked against two requirements (a tolerance band is a lower and an upper bound), and
those are two entries with the same part and attribute.
"""

from __future__ import annotations

from dataclasses import asdict, replace

import yaml

from app.projects.bds.confirm import _today, render_entry, write_entries
from app.projects.bds.gates import GateResult, check_proposal
from app.projects.bds.mapping import load_mapping
from app.projects.bds.model import BadTolerance, parse_tolerance
from app.projects.bds.proposals import Proposal
from app.projects.bds.verify import preview
from app.projects.bds.workspace import BdsError

MANUAL = "manual"


# -- Finding one entry in the text ------------------------------------------

def _blocks(lines, section):
    """(start, end) line spans of the list items of a top-level ``section``. An item is
    its ``- `` line plus the lines indented deeper; blank lines and comments between
    items belong to no item."""
    start = next((i for i, line in enumerate(lines) if line.rstrip("\r\n") == "%s:" % section), None)
    if start is None:
        return []
    spans, current, indent, stop = [], None, None, len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if line[:1] not in (" ", "\t", "\n", "\r", "") and not stripped.startswith("#"):
            stop = i                                # the next top-level key
            break
        width = len(line) - len(line.lstrip(" "))
        if stripped.startswith("- "):
            if current is not None:
                spans.append((current, i))
            current, indent = i, width
            continue
        if current is not None and (not stripped or stripped.startswith("#") or width <= indent):
            spans.append((current, i))
            current = None
    if current is not None:
        end = stop
        while end > current + 1 and not lines[end - 1].strip():
            end -= 1
        spans.append((current, end))
    return spans


def _load_item(lines, span):
    text = "".join(lines[span[0]:span[1]])
    data = yaml.safe_load(text)
    return data[0] if isinstance(data, list) and data else {}


def _find(lines, section, match):
    found = [(span, item) for span in _blocks(lines, section)
             for item in [_load_item(lines, span)] if match(item)]
    return found


def _attribute_match(part, attribute, requirement):
    return lambda item: (item.get("sysml_part") == part and item.get("attribute") == attribute
                         and (item.get("requirement") or "") == (requirement or ""))


def _write_checked(path, original, text, expect):
    """Write ``text``, read it back, keep it only if ``expect(mapping)`` holds."""
    path.write_text(text, encoding="utf-8")
    try:
        after = load_mapping(path)
        problem = expect(after)
        if problem:
            raise ValueError(problem)
    except Exception as exc:
        path.write_text(original, encoding="utf-8")
        raise BdsError(500, "bds_mapping_write_failed",
                       "Changing %s produced a file that does not read back as intended (%s). "
                       "The original has been restored -- nothing changed." % (path.name, exc)) from exc
    return after


def _one(path, part, attribute, requirement):
    if not path.is_file():
        raise BdsError(404, "bds_entry_not_found", "The workspace has no mapping yet")
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    found = _find(lines, "attributes", _attribute_match(part, attribute, requirement))
    if not found:
        raise BdsError(404, "bds_entry_not_found", "No mapping entry %s.%s%s"
                       % (part, attribute, " for %s" % requirement if requirement else " without a requirement"))
    if len(found) > 1:
        raise BdsError(409, "bds_entry_ambiguous", "%d mapping entries %s.%s for %r -- edit mapping.yaml by hand"
                       % (len(found), part, attribute, requirement or ""))
    return original, lines, found[0]


# -- The operations -----------------------------------------------------------

def create(workspace, catalog, requirements, pool, entry, dry_run=False, replaces=None):
    """A measurement chosen by hand -> {check, preview, written}. Gated exactly like a
    proposal; refused (409) when a gate says invalid.

    ``replaces``: the requirement ("" for none) of the entry (same part and attribute)
    this one takes the place of -- checked as if that entry were gone, and swapped in
    one step: if writing the new one fails, the old one is back."""
    requirement = entry.get("requirement") or ""
    part = entry["sysml_part"]
    if requirement and (requirement, part) not in requirements:
        raise BdsError(400, "bds_unknown_requirement",
                       "The model has no requirement %r on part %r" % (requirement, part),
                       {"requirements": sorted(r for r, p in requirements if p == part)})
    target = catalog.target(entry["cad_object"])
    proposal = Proposal(id=MANUAL, sysml_part=part, attribute=entry["attribute"],
                        adapter=target.adapter if target else "freecad", cad_object=entry["cad_object"],
                        method=entry["method"], args=dict(entry.get("args") or {}), requirement=requirement,
                        confidence=1.0, rationale="chosen by hand", proposed_by=MANUAL)
    mapping = load_mapping(workspace.mapping_path)
    if replaces is not None:
        _one(workspace.mapping_path, part, entry["attribute"], replaces)      # it has to exist
        mapping = _without(mapping, part, entry["attribute"], replaces)
    tolerance = entry.get("tolerance")
    check = check_proposal(proposal, mapping, catalog, requirements, pool)
    check = _tolerance_gate(check, tolerance, requirements.get((requirement, part)))
    result = {"check": check.to_dict(),
              "preview": preview(requirements.get((requirement, part)), check.measured, tolerance)}
    if dry_run:
        return {**result, "written": []}
    if check.verdict == "invalid":
        raise BdsError(409, "bds_gate_failed", "Not assigned: a check says this assignment is wrong.",
                       {"check": check.to_dict()})
    original = workspace.mapping_path.read_text(encoding="utf-8") if workspace.mapping_path.is_file() else None
    try:
        if replaces is not None:
            delete(workspace, part, entry["attribute"], replaces)
        written = write_entries(proposal, workspace.mapping_path, tolerance=tolerance,
                                note="chosen by hand, %s" % _today())
    except Exception:
        if original is not None:
            workspace.mapping_path.write_text(original, encoding="utf-8")
        raise
    return {**result, "written": written}


def _without(mapping, part, attribute, requirement):
    """The mapping with one attribute entry gone -- and its part entry, when no other
    attribute entry uses it (the replacement may name another object)."""
    attributes = [e for e in mapping.attributes
                  if (e.sysml_part, e.attribute, e.requirement or "") != (part, attribute, requirement or "")]
    parts = dict(mapping.parts)
    if not any(e.sysml_part == part for e in attributes):
        parts.pop(part, None)
    return replace(mapping, parts=parts, attributes=attributes)


def _tolerance_gate(check, tolerance, requirement):
    """A tolerance that cannot be read against the limit makes the assignment invalid
    (the gates read it from the entry, and a proposal carries none)."""
    if tolerance is None or requirement is None:
        return check
    try:
        parse_tolerance(tolerance, requirement.limit)
    except BadTolerance as exc:
        bad = GateResult("dimension", "invalid", str(exc))
        return replace(check, results=tuple(bad if r.gate == "dimension" else r for r in check.results))
    return check


def update(workspace, requirements, part, attribute, requirement, changes):
    """Relink the requirement and/or change the tolerance of one entry. ``changes`` holds
    only the keys to change: ``requirement`` ("" unlinks), ``tolerance`` (None removes)."""
    path = workspace.mapping_path
    original, lines, (span, item) = _one(path, part, attribute, requirement)
    new_requirement = changes.get("requirement", item.get("requirement") or "")
    if new_requirement and (new_requirement, part) not in requirements:
        raise BdsError(400, "bds_unknown_requirement",
                       "The model has no requirement %r on part %r" % (new_requirement, part),
                       {"requirements": sorted(r for r, p in requirements if p == part)})
    if "tolerance" in changes and changes["tolerance"] is not None and new_requirement:
        try:
            parse_tolerance(changes["tolerance"], requirements[(new_requirement, part)].limit)
        except BadTolerance as exc:
            raise BdsError(400, "bds_bad_tolerance", str(exc)) from exc
    updated = {**item, **{k: v for k, v in changes.items() if k in ("requirement", "tolerance")}}
    indent = lines[span[0]][: len(lines[span[0]]) - len(lines[span[0]].lstrip(" "))]
    text = "".join(lines[: span[0]]) + render_entry(updated, indent) + "".join(lines[span[1]:])

    def expect(after):
        hits = [e for e in after.attributes if (e.sysml_part, e.attribute, e.requirement or "")
                == (part, attribute, new_requirement)]
        if len(hits) != 1:
            return "expected one entry %s.%s for %r, found %d" % (part, attribute, new_requirement, len(hits))
        if "tolerance" in changes and hits[0].tolerance != changes["tolerance"]:
            return "tolerance reads back as %r" % (hits[0].tolerance,)
        return None

    after = _write_checked(path, original, text, expect)
    entry = next(e for e in after.attributes if (e.sysml_part, e.attribute, e.requirement or "")
                 == (part, attribute, new_requirement))
    return {"entry": asdict(entry)}


def delete(workspace, part, attribute, requirement):
    """Release one entry -> {removed: the entry as it was, part: the part entry if it
    went too}. The part entry goes when no attribute entry uses it any more -- what the
    caller needs to put both back (an undo is create() with the returned fields)."""
    path = workspace.mapping_path
    original, lines, (span, item) = _one(path, part, attribute, requirement)
    start = span[0] - 1 if span[0] > 0 and not lines[span[0] - 1].strip() else span[0]
    remaining = lines[:start] + lines[span[1]:]

    removed_part = None
    still_used = [e for e in _find(remaining, "attributes", lambda i: i.get("sysml_part") == part)]
    if not still_used:
        parts = _find(remaining, "parts", lambda i: i.get("sysml_part") == part)
        if len(parts) == 1:
            (pspan, removed_part) = parts[0]
            pstart = pspan[0] - 1 if pspan[0] > 0 and not remaining[pspan[0] - 1].strip() else pspan[0]
            remaining = remaining[:pstart] + remaining[pspan[1]:]
    before = load_mapping(path)
    text = "".join(remaining)

    def expect(after):
        gone = len(before.attributes) - len(after.attributes)
        if gone != 1:
            return "expected one attribute entry fewer, got %d" % gone
        if any((e.sysml_part, e.attribute, e.requirement or "") == (part, attribute, requirement or "")
               for e in after.attributes):
            return "the entry is still there"
        return None

    _write_checked(path, original, text, expect)
    return {"removed": item, "part": removed_part}
