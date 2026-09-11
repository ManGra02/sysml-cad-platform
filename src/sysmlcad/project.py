"""A project: one SysML model, and everything that ties it to CAD.

SRS FREQ-3, verbatim: "the mapping is stored with the project". A mapping is
the correspondence between ONE system model and its CAD; two models need two
mappings, and a run reads exactly one of them.

This module exists because the repository briefly did otherwise. When a second
model was published, its entries were appended to the first model's mapping and
the catalogue started merging every capture it could find -- so a proposer saw
two unrelated `Housing`s side by side, `verify api` checked whichever project
had been published most recently, and the answer key scored one proposer
against both models at once. None of that was a design; it was the path of
least resistance from one model to two. A `Project` is the concept that was
missing.

    projects/<name>/
        project.yaml        name, sysml_project
        mapping.yaml        the correspondence -- human-written, reviewed
        elements.json       an API capture of the model, for offline runs
        gold_mapping.yaml   the answer key for scoring proposers
        proposals.yaml      machine-written, read by no verification run

`project.yaml` holds two keys and nothing else; every other path is the
directory plus a fixed name. The one check on load is the one that matters: the
capture's Package must be the project it claims to be, so a mis-filed
`elements.json` fails loudly instead of quietly verifying the wrong model.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = ROOT / "projects"

#: How a CLI learns which project is meant when `--project` is not given.
#: There is no other fallback: guessing a project would be guessing which
#: model to verify.
PROJECT_ENV = "SYSMLCAD_PROJECT"


class UnknownProject(Exception):
    """Named a project that does not exist. The message lists those that do."""


@dataclass(frozen=True)
class Project:
    name: str
    sysml_project: str
    root: Path

    @property
    def mapping_path(self) -> Path:
        return self.root / "mapping.yaml"

    @property
    def elements_path(self) -> Path:
        return self.root / "elements.json"

    @property
    def gold_path(self) -> Path:
        return self.root / "gold_mapping.yaml"

    @property
    def proposals_path(self) -> Path:
        return self.root / "proposals.yaml"

    def elements(self) -> list[dict]:
        """The offline capture of this model, checked to be this model."""
        if not self.elements_path.is_file():
            raise FileNotFoundError(
                f"{self.name}: no capture at {self.elements_path}. Publish "
                f"{self.sysml_project!r}, then `python -m sysmlcad.explore "
                f"--project {self.name}` and copy the dump there."
            )
        elements = json.loads(self.elements_path.read_text(encoding="utf-8"))
        packages = sorted({
            e.get("declaredName") or "" for e in elements
            if e.get("@type") == "Package" and not e.get("isLibraryElement")
        })
        if self.sysml_project not in packages:
            raise ValueError(
                f"{self.elements_path} is not a capture of {self.sysml_project!r}: "
                f"it declares package(s) {packages or ['none']}. A mapping checked "
                f"against the wrong model would report confident verdicts about "
                f"the wrong parts."
            )
        return elements


def list_projects(projects_dir: Path = PROJECTS_DIR) -> list[str]:
    if not projects_dir.is_dir():
        return []
    return sorted(
        p.name for p in projects_dir.iterdir()
        if (p / "project.yaml").is_file()
    )


def load_project(name: str | None = None, projects_dir: Path = PROJECTS_DIR) -> Project:
    """`name` explicitly, else `SYSMLCAD_PROJECT`, else an error that lists them.

    No "the only one" or "the newest one" fallback. The whole point of a
    project is that which model gets verified is stated, not inferred.
    """
    name = name or os.environ.get(PROJECT_ENV)
    known = list_projects(projects_dir)

    if not name:
        raise UnknownProject(
            f"no project given. Pass --project <name>, set {PROJECT_ENV}, or use "
            f"`make ... PROJECT=<name>`. Available: {', '.join(known) or 'none'}"
        )
    if name not in known:
        raise UnknownProject(
            f"no project named {name!r} under {projects_dir}. "
            f"Available: {', '.join(known) or 'none'}"
        )

    root = projects_dir / name
    meta = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8")) or {}
    if meta.get("name") != name:
        raise ValueError(
            f"{root / 'project.yaml'} says name: {meta.get('name')!r}, "
            f"but the directory is {name!r}. One of them is wrong."
        )
    sysml_project = meta.get("sysml_project")
    if not sysml_project:
        raise ValueError(f"{root / 'project.yaml'} has no `sysml_project:` -- which model is this?")

    return Project(name=name, sysml_project=str(sysml_project), root=root)


def add_project_argument(parser) -> None:
    """The one `--project` flag every CLI shares, so the help text is the same."""
    parser.add_argument(
        "--project", "-p", metavar="NAME", default=None,
        help=f"which project (projects/<NAME>/); or set {PROJECT_ENV}. "
             f"Available: {', '.join(list_projects()) or 'none'}",
    )


def main() -> int:
    """`python -m sysmlcad.project` -- what exists."""
    names = list_projects()
    if not names:
        print(f"no projects under {PROJECTS_DIR}")
        return 1
    for name in names:
        project = load_project(name)
        has_capture = "capture" if project.elements_path.is_file() else "NO CAPTURE"
        has_mapping = "mapping" if project.mapping_path.is_file() else "NO MAPPING"
        print(f"  {name:<16} sysml_project={project.sysml_project:<14} {has_capture}, {has_mapping}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
