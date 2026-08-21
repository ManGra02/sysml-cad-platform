"""Duenner Client auf die SysML-v2-API-Services (Play, Port 9000).

Die Endpunkte folgen dem Pilot-PSM. Bevor du dich darauf verlaesst:
oeffne http://localhost:9000/docs/ und gleiche die Pfade ab -- das ist
der Realitaetstest aus Schritt 1.
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
            raise RuntimeError(f"Projekt {project_id} hat keine Commits")
        return commits[0]["@id"]

    def elements(self, project_id: str, commit_id: str) -> list[dict]:
        r = self._c.get(f"/projects/{project_id}/commits/{commit_id}/elements")
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._c.close()
