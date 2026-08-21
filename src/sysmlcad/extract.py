"""Requirement-Extraktion mit Fixture-Fallback.

Der Fallback ist Absicht: die CAD-Seite muss an Tag 1 testbar sein,
auch wenn der Java-Stack noch nicht laeuft. Sobald die API steht,
wird nur diese eine Datei erweitert -- alles dahinter bleibt gleich.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Requirement
from .sysml_client import SysMLClient

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "requirements.json"


def from_fixture(path: Path = FIXTURE) -> list[Requirement]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Requirement.from_dict(d) for d in data["requirements"]]


def from_api(project_id: str, base_url: str | None = None) -> list[Requirement]:
    client = SysMLClient(base_url)
    try:
        commit = client.head_commit(project_id)
        elements = client.elements(project_id, commit)
        return [r for r in (_to_requirement(e) for e in elements) if r]
    finally:
        client.close()


def _to_requirement(element: dict) -> Requirement | None:
    """Platzhalter fuer Phase 1.

    Hier wird aus dem RequirementDefinition-Element die Constraint gelesen.
    Die genaue Payload-Form haengt am API-Release -- erst gegen echte
    Antworten implementieren, nicht gegen eine Vermutung.
    """
    if element.get("@type") != "RequirementDefinition":
        return None
    raise NotImplementedError(
        "Phase 1: Payload-Struktur gegen die laufende API implementieren"
    )


def load(project_id: str | None = None) -> list[Requirement]:
    if project_id:
        return from_api(project_id)
    return from_fixture()
