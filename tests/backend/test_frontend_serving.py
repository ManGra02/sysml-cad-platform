"""M9: Auslieferung der gebauten Oberflaeche durch das Backend."""

import pytest_asyncio

from app import config
from conftest import running_backend


@pytest_asyncio.fixture
async def served(tmp_path, monkeypatch, handshake):
    static = tmp_path / "static"
    monkeypatch.setattr(config, "STATIC_DIR", static)
    async with running_backend() as handle:
        handle.static = static
        yield handle


def build(static, marker="v1"):
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text(
        '<!doctype html><title>SysML-CAD Platform</title><script src="/assets/index-%s.js"></script>' % marker,
        encoding="utf-8",
    )
    (static / "assets" / ("index-%s.js" % marker)).write_text("console.log(%r)" % marker, encoding="utf-8")


async def test_ohne_build_hinweisseite_und_status(served):
    async with served.http.get(served.url + "/") as response:
        assert response.status == 200
        assert "noch nicht gebaut" in await response.text()
    _, status = await served.get("/api/status")
    assert status["frontend"] == {"built": False, "builtAt": None}


async def test_fehlende_assets_sind_404_nicht_500(served):
    async with served.http.get(served.url + "/assets/index-x.js") as response:
        assert response.status == 404


async def test_build_ohne_neustart_ausgeliefert(served):
    """pnpm build bei laufendem Backend -- die neue Oberflaeche ist sofort da."""
    async with served.http.get(served.url + "/assets/index-v1.js") as response:
        assert response.status == 404
    build(served.static)
    async with served.http.get(served.url + "/cad/Doc?obj=Box") as response:
        assert response.status == 200
        assert "index-v1.js" in await response.text()
    async with served.http.get(served.url + "/assets/index-v1.js") as response:
        assert response.status == 200
    _, status = await served.get("/api/status")
    assert status["frontend"]["built"] is True and status["frontend"]["builtAt"] > 0


async def test_cache_regeln(served):
    build(served.static)
    async with served.http.get(served.url + "/") as response:
        assert response.headers["Cache-Control"] == "no-cache"
    async with served.http.get(served.url + "/projects/bds") as response:
        assert response.headers["Cache-Control"] == "no-cache"
    async with served.http.get(served.url + "/assets/index-v1.js") as response:
        assert "immutable" in response.headers["Cache-Control"]


async def test_assets_bleiben_im_verzeichnis(served):
    build(served.static)
    (served.static / "geheim.txt").write_text("nicht ausliefern", encoding="utf-8")
    for path in ("/assets/../geheim.txt", "/assets/..%2Fgeheim.txt", "/assets/%2e%2e/geheim.txt"):
        async with served.http.get(served.url + path) as response:
            assert "nicht ausliefern" not in await response.text(), path
