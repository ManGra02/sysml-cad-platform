"""A FreeCAD-mapped project end to end: verify, gates, and writing limits back.

Runs on a COPY of `projects/cube_freecad` whose mapping points at a FreeCAD
document through the stand-in worker in `freecad_fake.py`. Three questions:

* does a run check requirements against a stated dimension (`parameter`)?
* does a missing worker cost those requirements and nothing else?
* does `sync` write limits -- and only limits, only when asked, only into a
  sheet it owns -- and leave a record when it does?
"""

import json
import shutil

import pytest

from freecad_fake import FakeWorker, cube_document
from sysmlcad import sync as sync_module
from sysmlcad import verify
from sysmlcad.adapters.freecad_adapter import URL_ENV, FreeCadAdapter
from sysmlcad.gates import check_mapping
from sysmlcad.project import PROJECTS_DIR, load_project
from sysmlcad.verify import AdapterPool

DOCUMENT = "projects/cube_freecad/cube.FCStd"

MAPPING = """\
version: 2
parts:
  - sysml_part: box2
    adapter: freecad
    cad_object: {document}
    status: confirmed
    author: test
    confirmed_at: "2026-10-08"
attributes:
  - sysml_part: box2
    attribute: length
    requirement: MaxLength
    method: parameter
    args: {{name: Params.Length}}
    direction: {direction}
    status: confirmed
  - sysml_part: box2
    attribute: width
    requirement: MaxWidth
    method: parameter
    args: {{name: Params.Width}}
    direction: cad_owns
    status: confirmed
  - sysml_part: box2
    attribute: height
    requirement: MaxHeight
    method: bbox_size
    args: {{axis: Z}}
    direction: cad_owns
    status: confirmed
"""


@pytest.fixture
def root(tmp_path):
    return tmp_path


@pytest.fixture
def worker():
    return FakeWorker(documents={DOCUMENT: cube_document()})


def _project(root, direction="cad_owns"):
    target = root / "projects" / "cube_freecad"
    shutil.copytree(PROJECTS_DIR / "cube_freecad", target)
    (target / "cube.FCStd").write_bytes(b"PK fake FCStd")
    (target / "mapping.yaml").write_text(
        MAPPING.format(document=DOCUMENT, direction=direction), encoding="utf-8"
    )
    return load_project("cube_freecad", projects_dir=root / "projects")


@pytest.fixture
def project(root):
    return _project(root)


@pytest.fixture
def wired(root, worker, monkeypatch):
    """Every AdapterPool in this test gets the stand-in worker."""
    monkeypatch.setitem(
        verify.ADAPTERS, "freecad",
        lambda: FreeCadAdapter(url="http://freecad.test", transport=worker.transport(), root=root),
    )
    return worker


# --------------------------------------------------------------------------
# Verify and gates
# --------------------------------------------------------------------------

def test_a_run_checks_requirements_against_the_stated_dimensions(project, wired):
    run = verify.run(project)
    assert run.gaps == []
    by_id = {v.requirement.requirement_id: v for v in run.verdicts}
    assert by_id["MaxLength"].measured.to("mm").magnitude == 100
    assert by_id["MaxLength"].status == "compliant"
    assert "parameter" in by_id["MaxLength"].method
    assert all(v.status == "compliant" for v in run.verdicts)
    assert run.context.cad_state_id.startswith("freecad:")


def test_without_a_worker_the_freecad_requirements_are_gaps_not_a_crash(project, root, monkeypatch):
    monkeypatch.delenv(URL_ENV, raising=False)
    monkeypatch.setitem(verify.ADAPTERS, "freecad", lambda: FreeCadAdapter(root=root))
    run = verify.run(project)
    assert run.verdicts == []
    assert len(run.gaps) == 3
    assert all(URL_ENV in gap for gap in run.gaps)


def test_a_parameter_mapping_passes_every_gate(project, wired):
    checks = check_mapping(project)
    assert [c.verdict for c in checks] == ["valid", "valid", "valid"], [
        (c.attribute, [(g.gate, g.verdict, g.detail) for g in c.results]) for c in checks
    ]


# --------------------------------------------------------------------------
# Writing limits back
# --------------------------------------------------------------------------

def _sync(project, root, apply=False):
    log = root / "out" / "sync_log.jsonl"
    code = sync_module.sync(project, apply=apply, pool=AdapterPool(), log=log, root=root)
    return code, log


def test_the_dry_run_shows_the_diff_and_writes_nothing(project, root, wired, capsys):
    code, log = _sync(project, root)
    out = capsys.readouterr().out
    assert code == 0
    assert "SysML.MaxLength" in out and "(new) -> 100 mm" in out
    assert "dry run" in out
    assert wired.documents[DOCUMENT].sheets == {}
    assert not log.exists()


def test_apply_writes_every_limit_and_leaves_a_record(project, root, wired):
    code, log = _sync(project, root, apply=True)
    assert code == 0
    cells = wired.documents[DOCUMENT].sheets["SysML"]["cells"]
    assert set(cells) == {"MaxLength", "MaxWidth", "MaxHeight"}

    [record] = [json.loads(line) for line in log.read_text().splitlines()]
    assert record["project"] == "cube_freecad"
    assert record["document"] == DOCUMENT
    assert record["digest_before"]
    assert {c["alias"]: c["new"] for c in record["changes"]}["MaxLength"] == "100 mm"


def test_a_second_sync_of_an_unchanged_model_has_nothing_to_say(project, root, wired, capsys):
    _sync(project, root, apply=True)
    capsys.readouterr()
    code, log = _sync(project, root, apply=True)
    assert code == 0
    assert "0 change(s) written" in capsys.readouterr().out
    assert len(log.read_text().splitlines()) == 1


def test_a_value_sysml_owns_is_held_back_and_only_its_limit_written(root, wired, capsys):
    project = _project(root, direction="sysml_owns")
    _sync(project, root, apply=True)
    out = capsys.readouterr().out
    assert "HELD BACK box2.length" in out
    cells = wired.documents[DOCUMENT].sheets["SysML"]["cells"]
    assert "MaxLength" in cells                 # the limit, yes
    assert "Params.Length" not in cells         # the value it constrains, never


def test_a_sheet_somebody_else_owns_fails_the_sync(project, root, wired, capsys):
    wired.documents[DOCUMENT].sheets["SysML"] = {"managed": False, "cells": {}}
    code, log = _sync(project, root, apply=True)
    assert code == 1
    assert "NOT WRITTEN" in capsys.readouterr().out
    assert not log.exists()


def test_a_project_without_freecad_has_nothing_to_write(capsys):
    """motor_housing maps onto a script; there is nowhere to put a limit."""
    code = sync_module.sync(load_project("motor_housing"), pool=AdapterPool())
    assert code == 0
    assert "nothing to write" in capsys.readouterr().out
