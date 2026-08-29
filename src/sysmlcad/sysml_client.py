"""A thin client for the SysML v2 API Services (Play, port 9000).

The endpoints follow the pilot PSM. Before relying on them, open
http://localhost:9000/docs/ and check the paths against the running
server -- the specification and the implementation do drift.
"""

from __future__ import annotations

import httpx

from .config import SYSML_API_URL


class SysMLClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        base_url = base_url or SYSML_API_URL
        self._c = httpx.Client(base_url=base_url, timeout=timeout)

    def ping(self) -> bool:
        try:
            return self._c.get("/projects").status_code < 500
        except httpx.HTTPError:
            return False

    def projects(self) -> list[dict]:
        r = self._c.get("/projects")
        r.raise_for_status()
        return r.json()

    def head_commit(self, project_id: str) -> str:
        r = self._c.get(f"/projects/{project_id}/commits")
        r.raise_for_status()
        commits = r.json()
        if not commits:
            raise RuntimeError(f"project {project_id} has no commits")
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
