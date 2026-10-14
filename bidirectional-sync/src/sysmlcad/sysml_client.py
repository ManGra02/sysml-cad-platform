"""A thin client for the SysML v2 API Services (Play, port 9000).

The endpoints follow the pilot PSM. Before relying on them, open
http://localhost:9000/docs/ and check the paths against the running
server -- the specification and the implementation do drift.
"""

from __future__ import annotations

import httpx

from .config import SYSML_API_URL


class SysMLClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        """`transport` exists for tests: an `httpx.MockTransport` stands in for
        the server, so the client's own logic runs with no network."""
        base_url = base_url or SYSML_API_URL
        self._c = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def ping(self) -> bool:
        try:
            return self._c.get("/projects").status_code < 500
        except httpx.HTTPError:
            return False

    def projects(self) -> list[dict]:
        r = self._c.get("/projects")
        r.raise_for_status()
        return r.json()

    def project_named(self, name: str) -> dict:
        """The server project called `name` -- BY NAME, never "the newest one".

        Publishing the same package twice leaves two projects with one name.
        Then the newest of THOSE is taken -- same name, so the same model --
        and a warning says so, because a silent choice here is a silent choice
        of commit. One implementation, so the verifier, the catalogue and the
        explorer cannot disagree about which project a name means.
        """
        projects = self.projects()
        matching = [p for p in projects if p.get("name") == name]
        if not matching:
            available = ", ".join(sorted(p.get("name", "?") for p in projects)) or "none"
            raise LookupError(
                f"no project named {name!r} on the API server. Available: {available}"
            )
        if len(matching) > 1:
            print(f"[warn] {len(matching)} server projects named {name!r}; "
                  f"using the most recently created")
        return sorted(matching, key=lambda p: p.get("created", ""))[-1]

    def head_commit(self, project_id: str) -> str:
        """The head of the project's default branch -- the model state a run
        should cite.

        It used to be `commits[0]` of `/projects/{id}/commits`, which assumes the
        server lists the newest commit first. Checked against the live server
        (2026-09-26): with one commit per project the two agree, but nothing
        promises that order once a project has several. The branch names its
        head explicitly. The commit list is only a fallback, and only when it
        has exactly one entry -- picking one of several would be guessing
        which model state gets verified.
        """
        r = self._c.get(f"/projects/{project_id}")
        r.raise_for_status()
        branch_id = (r.json().get("defaultBranch") or {}).get("@id")
        if branch_id:
            r = self._c.get(f"/projects/{project_id}/branches/{branch_id}")
            r.raise_for_status()
            head = (r.json().get("head") or {}).get("@id")
            if head:
                return head

        r = self._c.get(f"/projects/{project_id}/commits")
        r.raise_for_status()
        commits = r.json()
        if not commits:
            raise RuntimeError(f"project {project_id} has no commits")
        if len(commits) > 1:
            raise RuntimeError(
                f"project {project_id} has {len(commits)} commits and no default "
                f"branch head -- refusing to guess which one is current"
            )
        return commits[0]["@id"]

    def elements(self, project_id: str, commit_id: str) -> list[dict]:
        """The FIRST page only (100 elements by default)."""
        r = self._c.get(f"/projects/{project_id}/commits/{commit_id}/elements")
        r.raise_for_status()
        return r.json()

    def all_elements(self, project_id: str, commit_id: str, page_size: int = 200) -> list[dict]:
        """Every page. The API links the next one in the Link header --
        ignoring it means silently working on a partial model."""
        url = f"/projects/{project_id}/commits/{commit_id}/elements?page[size]={page_size}"
        out: list[dict] = []
        while url:
            r = self._c.get(url)
            r.raise_for_status()
            out.extend(r.json())
            nxt = r.links.get("next")
            url = nxt["url"] if nxt else None
        return out

    def close(self) -> None:
        self._c.close()
