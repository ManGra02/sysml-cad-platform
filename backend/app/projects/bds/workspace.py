"""A workspace: one SysML model, one FreeCAD document, and the mapping between them.

    data/bds/<name>/                  (BDS_DATA_DIR overrides data/bds)
        workspace.yaml      sysml_project, cad_document, optional axes / limits_sheet
        mapping.yaml        the correspondence -- reviewed, the only thing a run reads
        proposals.yaml      machine-written candidates, read by no run
        gold_mapping.yaml   optional answer key for scoring proposers
        sync_log.jsonl      every limit written into FreeCAD

A mapping belongs to ONE model: two models need two workspaces, and a run reads
exactly one of them.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.projects.bds import mapping as mapping_mod

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "bds"

#: Which bounding-box axis a named dimension lies along, unless the workspace says
#: otherwise. A convention, not a standard: FreeCAD puts a box's Length, Width and
#: Height on X, Y and Z; other CAD systems differ (Chili3D: length Y, width Z,
#: height X), which is why ``axes:`` can override any of these.
DEFAULT_AXES = {
    "length": "X", "long": "X", "depth": "X",
    "width": "Y", "breadth": "Y",
    "height": "Z", "thickness": "Z", "tall": "Z",
}

#: The spreadsheet SysML's limits are written into, so a designer can use
#: ``=SysML.MaxLength`` in an expression. A sheet the sync owns, never one a
#: designer keeps parameters in.
DEFAULT_LIMITS_SHEET = "SysML"

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_SHEET = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class BdsError(Exception):
    def __init__(self, status, code, message, detail=None):
        super().__init__("%s: %s" % (code, message))
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


def data_dir():
    override = os.environ.get("BDS_DATA_DIR")
    return Path(override) if override else DATA_DIR


@dataclass(frozen=True)
class Workspace:
    name: str
    sysml_project: str
    root: Path
    cad_document: str = ""
    axes: dict = field(default_factory=lambda: dict(DEFAULT_AXES), hash=False)
    limits_sheet: str = DEFAULT_LIMITS_SHEET

    @property
    def mapping_path(self):
        return self.root / "mapping.yaml"

    @property
    def proposals_path(self):
        return self.root / "proposals.yaml"

    @property
    def gold_path(self):
        return self.root / "gold_mapping.yaml"

    @property
    def sync_log_path(self):
        return self.root / "sync_log.jsonl"

    def settings(self):
        """What workspace.yaml holds -- axes only where they differ from the default."""
        axes = {k: v for k, v in self.axes.items() if DEFAULT_AXES.get(k) != v}
        out = {"name": self.name, "sysml_project": self.sysml_project,
               "cad_document": self.cad_document, "limits_sheet": self.limits_sheet}
        if axes:
            out["axes"] = axes
        return out

    @property
    def last_run_path(self):
        return self.root / "last_run.json"

    def last_run(self):
        """The most recent verification result (only that one -- no history), or None."""
        if not self.last_run_path.is_file():
            return None
        try:
            return json.loads(self.last_run_path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def save_last_run(self, result):
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_run_path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    def counts(self):
        from app.projects.bds.proposals import load_proposals

        try:
            mapping = mapping_mod.load_mapping(self.mapping_path)
            parts = sum(1 for p in mapping.parts.values() if p.usable)
            attributes = sum(1 for a in mapping.attributes if a.usable)
        except (ValueError, TypeError):
            parts = attributes = None          # a hand-edited mapping that does not load
        pending = sum(1 for p in load_proposals(self.proposals_path) if p.pending)
        return {"parts_confirmed": parts, "attributes_confirmed": attributes, "proposals_pending": pending}

    def to_dict(self):
        last = self.last_run()
        return {**self.settings(), "axes": dict(self.axes),
                "mapping": self.mapping_path.is_file(),
                "proposals": self.proposals_path.is_file(),
                "gold": self.gold_path.is_file(),
                "counts": self.counts(),
                "last_run": {k: last.get(k) for k in ("summary", "violated", "context")} if last else None}


def _check_name(name):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise BdsError(400, "bds_invalid_name",
                             "Workspace name %r: letters, digits, '_', '-', '.'" % (name,))


def _axes(configured):
    """DEFAULT_AXES with the workspace's own on top. Refused rather than guessed when
    malformed: a silently defaulted convention would measure the wrong extent."""
    axes = dict(DEFAULT_AXES)
    if configured is None:
        return axes
    if not isinstance(configured, dict):
        raise BdsError(400, "bds_invalid_axes", "axes must map dimension names to X, Y or Z")
    for name, axis in configured.items():
        value = str(axis).upper()
        if value not in ("X", "Y", "Z"):
            raise BdsError(400, "bds_invalid_axes", "axes.%s is %r, expected X, Y or Z" % (name, axis))
        axes[str(name).lower()] = value
    main = [axes["length"], axes["width"], axes["height"]]
    if len(set(main)) != 3:
        raise BdsError(400, "bds_invalid_axes",
                             "length, width and height must lie on three different axes, not %s" % main)
    return axes


def _sheet(value):
    sheet = value or DEFAULT_LIMITS_SHEET
    if not isinstance(sheet, str) or not _SHEET.fullmatch(sheet):
        raise BdsError(400, "bds_invalid_sheet",
                             "limits_sheet %r must be a plain name -- it is what =%s.MaxLength refers to"
                             % (sheet, sheet))
    return sheet


def list_workspaces():
    root = data_dir()
    if not root.is_dir():
        return []
    return [load_workspace(p.name) for p in sorted(root.iterdir()) if (p / "workspace.yaml").is_file()]


def load_workspace(name):
    _check_name(name)
    root = data_dir() / name
    path = root / "workspace.yaml"
    if not path.is_file():
        raise BdsError(404, "bds_workspace_not_found", "No BDS workspace %r" % name,
                             {"available": [w.name for w in list_workspaces()]})
    meta = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not meta.get("sysml_project"):
        raise BdsError(400, "bds_invalid_workspace", "%s has no sysml_project" % path)
    return Workspace(name=name, sysml_project=str(meta["sysml_project"]), root=root,
                     cad_document=str(meta.get("cad_document") or ""),
                     axes=_axes(meta.get("axes")), limits_sheet=_sheet(meta.get("limits_sheet")))


def save_workspace(name, sysml_project, cad_document="", axes=None, limits_sheet=None):
    """Create or update a workspace; a new one starts with an empty mapping."""
    _check_name(name)
    if not sysml_project:
        raise BdsError(400, "bds_invalid_workspace", "sysml_project is required")
    workspace = Workspace(name=name, sysml_project=sysml_project, root=data_dir() / name,
                          cad_document=cad_document or "", axes=_axes(axes),
                          limits_sheet=_sheet(limits_sheet))
    workspace.root.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(workspace.settings(), sort_keys=False, allow_unicode=True)
    (workspace.root / "workspace.yaml").write_text(body, encoding="utf-8")
    if not workspace.mapping_path.is_file():
        workspace.mapping_path.write_text(mapping_mod.EMPTY, encoding="utf-8")
    return workspace
