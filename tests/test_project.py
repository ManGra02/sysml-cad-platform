"""The project: one model, one mapping, and no guessing which.

These pin the refusals more than the happy path. Every one of them is a way the
old arrangement went wrong silently -- the newest server project being verified
instead of the intended one, a capture of one model sitting under another
model's mapping, two models' parts merged into one catalogue -- and each is now
a loud error instead.
"""

import json

import pytest

from sysmlcad.project import (
    PROJECT_ENV,
    UnknownProject,
    list_projects,
    load_project,
)


# --------------------------------------------------------------------------
# Finding a project
# --------------------------------------------------------------------------

def test_both_committed_projects_load():
    assert list_projects() == ["gearbox", "motor_housing"]
    for name in list_projects():
        project = load_project(name)
        assert project.name == name
        assert project.mapping_path.is_file()
        assert project.elements_path.is_file()
        assert project.gold_path.is_file()


def test_the_sysml_project_name_is_the_package_name():
    assert load_project("motor_housing").sysml_project == "MotorHousing"
    assert load_project("gearbox").sysml_project == "Gearbox"


def test_an_unknown_project_lists_the_known_ones():
    with pytest.raises(UnknownProject, match="gearbox, motor_housing"):
        load_project("turbine")


def test_no_project_is_an_error_not_a_default(monkeypatch):
    """There is no "the only one" or "the newest one" fallback. Which model
    gets verified is stated, never inferred -- inferring it from publish order
    is exactly how the wrong model got verified before."""
    monkeypatch.delenv(PROJECT_ENV, raising=False)
    with pytest.raises(UnknownProject, match=PROJECT_ENV):
        load_project(None)


def test_the_environment_can_name_the_project(monkeypatch):
    monkeypatch.setenv(PROJECT_ENV, "gearbox")
    assert load_project(None).name == "gearbox"


def test_an_explicit_name_beats_the_environment(monkeypatch):
    monkeypatch.setenv(PROJECT_ENV, "gearbox")
    assert load_project("motor_housing").name == "motor_housing"


# --------------------------------------------------------------------------
# The capture must be the model it claims to be
# --------------------------------------------------------------------------

def _project_dir(tmp_path, name, sysml_project, elements):
    root = tmp_path / name
    root.mkdir()
    (root / "project.yaml").write_text(
        f"name: {name}\nsysml_project: {sysml_project}\n", encoding="utf-8"
    )
    (root / "elements.json").write_text(json.dumps(elements), encoding="utf-8")
    return root


def test_a_capture_of_another_model_is_refused(tmp_path):
    """A gearbox capture filed under the motor housing would verify the wrong
    model with the motor housing's mapping -- confidently, and about the wrong
    parts. The package in the capture is the tell, and it is checked."""
    gearbox = json.loads(load_project("gearbox").elements_path.read_text(encoding="utf-8"))
    _project_dir(tmp_path, "motor_housing", "MotorHousing", gearbox)

    project = load_project("motor_housing", projects_dir=tmp_path)
    with pytest.raises(ValueError, match="not a capture of 'MotorHousing'"):
        project.elements()


def test_a_capture_with_no_package_is_refused(tmp_path):
    _project_dir(tmp_path, "empty", "Empty", [{"@type": "Feature", "@id": "x"}])
    with pytest.raises(ValueError, match="none"):
        load_project("empty", projects_dir=tmp_path).elements()


def test_a_missing_capture_says_how_to_make_one(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "project.yaml").write_text("name: fresh\nsysml_project: Fresh\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="explore --project fresh"):
        load_project("fresh", projects_dir=tmp_path).elements()


# --------------------------------------------------------------------------
# project.yaml must agree with its directory
# --------------------------------------------------------------------------

def test_a_name_that_disagrees_with_the_directory_is_refused(tmp_path):
    """Copying a project directory and forgetting to edit project.yaml would
    leave two projects claiming one name. Caught at load."""
    _project_dir(tmp_path, "copy", "Copy", [])
    (tmp_path / "copy" / "project.yaml").write_text(
        "name: original\nsysml_project: Copy\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="directory is 'copy'"):
        load_project("copy", projects_dir=tmp_path)


def test_a_project_without_a_model_name_is_refused(tmp_path):
    root = tmp_path / "anon"
    root.mkdir()
    (root / "project.yaml").write_text("name: anon\n", encoding="utf-8")
    with pytest.raises(ValueError, match="which model is this"):
        load_project("anon", projects_dir=tmp_path)


def test_a_directory_without_project_yaml_is_not_a_project(tmp_path):
    (tmp_path / "stray").mkdir()
    (tmp_path / "stray" / "mapping.yaml").write_text("version: 2\n", encoding="utf-8")
    assert list_projects(tmp_path) == []
