""".sysml import: the package scan offline, the importer against fake_kernel + fake_flexo,
POST /api/sysml/import and importAvailable in /api/sysml/status.

The real kernel (a JVM in Docker) is not needed: fake_kernel.FakeKernel answers the cells
with the texts the real one prints.
"""

import pytest
import pytest_asyncio

from app.sysml.client import SysmlError
from app.sysml.config import SysmlConfig
from app.sysml.demo import SAMPLES_DIR
from app.sysml.importer import free_project_name, plain_name, top_level_packages
from app.sysml.service import SysmlService
from conftest import free_port, running_backend
from fake_flexo import FakeFlexo
from fake_kernel import FakeKernel

CUBE = (SAMPLES_DIR / "cube_freecad.sysml").read_text(encoding="utf-8")


# -- Package scan (offline) ----------------------------------------------


def test_beispieldatei_hat_ein_package():
    assert top_level_packages(CUBE) == ["CubeFreecad"]


def test_package_scan_ignoriert_kommentare_und_verschachtelung():
    text = """// package InComment {
    /* package InBlock */
    library package <'p1'> 'My {Pkg}' {
        package Inner { doc /* package InDoc */ }
        attribute s = "package InString { ";
    }
    standard library package Lib;"""
    assert top_level_packages(text) == ["'My {Pkg}'", "Lib"]
    assert top_level_packages("part def X; subpackage Y;") == []


def test_namen():
    assert plain_name("'My \\'Pkg\\''") == "My 'Pkg'"
    assert plain_name("Box") == "Box"
    assert free_project_name("Box", ["box", "Box (2)", None]) == "Box (3)"
    assert free_project_name("Box", ["Other"]) == "Box"


# -- The importer against the stand-ins ----------------------------------


@pytest_asyncio.fixture
async def stack():
    flexo = FakeFlexo()
    flexo.url = await flexo.start()
    kernel = FakeKernel(flexo)
    await kernel.start()
    service = SysmlService(SysmlConfig(api_url=flexo.url, timeout_s=5, kernel_url=kernel.url,
                                       kernel_target="http://flexo-sysmlv2:8080"))
    yield service, kernel, flexo
    await service.stop()
    await kernel.stop()
    await flexo.stop()


async def test_import_legt_ein_neues_projekt_an(stack):
    service, kernel, _ = stack
    result = await service.import_sysml(CUBE)
    assert (result["package"], result["projectName"]) == ("CubeFreecad", "CubeFreecad")
    assert kernel.cells[0] == "%repo http://flexo-sysmlv2:8080"    # never the kernel's default server
    assert kernel.cells[1] == CUBE
    assert kernel.cells[2] == '%publish -d --project="CubeFreecad" CubeFreecad'
    assert not kernel.kernels                                     # shut down after the import
    snap = await service.snapshot(result["projectId"])
    assert snap.version == result["commitId"]

    again = await service.import_sysml(CUBE)                      # same package: a new project, not a commit
    assert again["projectName"] == "CubeFreecad (2)" and again["projectId"] != result["projectId"]
    named = await service.import_sysml(CUBE, project_name="My Cube")
    assert named["projectName"] == "My Cube"
    assert len(await service.projects()) == 3


async def test_syntaxfehler(stack):
    service, kernel, _ = stack
    with pytest.raises(SysmlError) as info:
        await service.import_sysml("package Bad {\n  part def X\n  part !! y;\n}")
    assert (info.value.status, info.value.code) == (422, "sysml_import_syntax")
    assert info.value.message == "no viable alternative at input '!!' (line 3, column 5)"
    assert len(kernel.cells) == 2 and not kernel.kernels          # %publish never ran
    assert await service.projects() == []


async def test_kein_oder_mehrere_packages(stack):
    service, kernel, _ = stack
    for text in ("part def X;", "package A; package B;"):
        with pytest.raises(SysmlError) as info:
            await service.import_sysml(text)
        assert (info.value.status, info.value.code) == (400, "sysml_import_package")
    assert kernel.cells == []


async def test_falsches_ziel_wird_gemeldet(stack):
    service, kernel, _ = stack
    kernel.report_target = "https://sysml2.intercax.com:9000"
    with pytest.raises(SysmlError) as info:
        await service.import_sysml(CUBE)
    assert info.value.code == "sysml_import_wrong_target"


async def test_kernel_nicht_erreichbar(stack):
    service, _, _ = stack
    service.config.kernel_url = "http://127.0.0.1:%d" % free_port()
    with pytest.raises(SysmlError) as info:
        await service.import_sysml(CUBE)
    assert (info.value.status, info.value.code) == (503, "sysml_kernel_unreachable")
    assert (await service.status())["importAvailable"] is False


async def test_falsches_token(stack):
    service, _, _ = stack
    service.config.kernel_token = "wrong"
    with pytest.raises(SysmlError) as info:
        await service.import_sysml(CUBE)
    assert info.value.code == "sysml_kernel_unauthorized"


# -- /api/sysml/import ----------------------------------------------------


async def test_api_import(handshake, stack):
    service, _, _ = stack
    async with running_backend(sysml_service=service) as backend:
        code, status = await backend.get("/api/sysml/status")
        assert code == 200 and status["importAvailable"] is True

        code, body = await backend.post("/api/sysml/import", json={"filename": "cube.sysml", "text": CUBE})
        assert code == 200 and body["projectName"] == "CubeFreecad"
        code, projects = await backend.get("/api/sysml/projects")
        assert [p["id"] for p in projects] == [body["projectId"]]

        code, body = await backend.post("/api/sysml/import", json={"text": "package X { !! }"})
        assert code == 422 and body["error"]["code"] == "sysml_import_syntax"
        assert body["error"]["detail"]["errors"]
