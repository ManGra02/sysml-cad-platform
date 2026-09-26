"""The SysML v2 API client, against a stand-in server.

`httpx.MockTransport` answers the requests, so the client's own decisions run
with no network: which project a name means, and which commit is current. Both
are choices of *which model state gets verified*, and a wrong one produces
confident verdicts about the wrong model.
"""

import httpx
import pytest

from sysmlcad.sysml_client import SysMLClient


def _client(routes: dict[str, object]) -> SysMLClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=body)

    return SysMLClient("http://sysml.test", transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------
# Which commit is current
# --------------------------------------------------------------------------

def test_the_head_is_the_default_branch_head_not_the_first_commit():
    """The commit list is in whatever order the server likes. The branch says
    which commit is its head; that is the state a run must cite."""
    client = _client({
        "/projects/p": {"@id": "p", "defaultBranch": {"@id": "b"}},
        "/projects/p/branches/b": {"@id": "b", "head": {"@id": "c2"}},
        "/projects/p/commits": [{"@id": "c1"}, {"@id": "c2"}],
    })
    assert client.head_commit("p") == "c2"


def test_without_a_branch_a_single_commit_is_the_head():
    client = _client({
        "/projects/p": {"@id": "p"},
        "/projects/p/commits": [{"@id": "c1"}],
    })
    assert client.head_commit("p") == "c1"


def test_without_a_branch_several_commits_are_refused():
    """Taking the first of several would be guessing which model state gets
    verified."""
    client = _client({
        "/projects/p": {"@id": "p"},
        "/projects/p/commits": [{"@id": "c1"}, {"@id": "c2"}],
    })
    with pytest.raises(RuntimeError, match="refusing to guess"):
        client.head_commit("p")


def test_a_project_without_commits_is_an_error():
    client = _client({"/projects/p": {"@id": "p"}, "/projects/p/commits": []})
    with pytest.raises(RuntimeError, match="no commits"):
        client.head_commit("p")


# --------------------------------------------------------------------------
# Which project a name means
# --------------------------------------------------------------------------

def test_a_project_is_found_by_name_not_by_recency():
    client = _client({"/projects": [
        {"@id": "old", "name": "MotorHousing", "created": "2026-09-01T00:00:00Z"},
        {"@id": "other", "name": "Gearbox", "created": "2026-09-09T00:00:00Z"},
    ]})
    assert client.project_named("MotorHousing")["@id"] == "old"


def test_the_same_name_twice_takes_the_newest_and_says_so(capsys):
    client = _client({"/projects": [
        {"@id": "new", "name": "Gearbox", "created": "2026-09-03T23:25:08Z"},
        {"@id": "old", "name": "Gearbox", "created": "2026-09-03T19:00:00Z"},
    ]})
    assert client.project_named("Gearbox")["@id"] == "new"
    assert "2 server projects named 'Gearbox'" in capsys.readouterr().out


def test_an_unknown_name_lists_what_exists():
    client = _client({"/projects": [{"@id": "g", "name": "Gearbox"}]})
    with pytest.raises(LookupError, match="Available: Gearbox"):
        client.project_named("Turbine")
