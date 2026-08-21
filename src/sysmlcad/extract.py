"""Requirement-Extraktion aus der SysML-v2-API.

=============================================================================
BEWUSSTE VEREINFACHUNGEN (Phase 1)
=============================================================================
Dieser Extraktor liest NICHT das vollstaendige Metamodell. Er sucht in der
von einer RequirementDefinition aus erreichbaren Teilmenge nach drei Dingen:

    1. OPERATOR  -- erste OperatorExpression mit einem Vergleichsoperator
                    (<=, >=, <, >, ==). Bei uns liefert das die ConstraintUsage
                    unterhalb der RequirementConstraintMembership.
    2. GRENZWERT -- erstes Literal (LiteralInteger / LiteralRational) mit
                    einem "value"-Feld. Bei uns die 120 bzw. 0.9 aus dem
                    AttributeUsage maxLength / maxMass.
    3. EINHEIT   -- erstes AttributeUsage mit isLibraryElement=true und
                    declaredShortName ("mm", "kg"). Die Einheit steht im
                    Modell NICHT als Feld, sondern als OperatorExpression mit
                    operator="[", deren zweiter Operand auf das Einheiten-
                    Element der Standardbibliothek zeigt.

Was hier NICHT passiert, und warum:

    * Die gemessene GROESSE (length, mass) wird nicht aus dem Ausdruck
      "housing.length <= maxLength" geparst. Sie kommt aus mapping.yaml.
      Begruendung: Welche CAD-Groesse wie gemessen wird, ist Mapping-Wissen
      und steht dort ohnehin. Der Constraint-Baum haette dafuer eine
      Aufloesung der FeatureChainExpression erfordert.
      KOSTEN: Schreibt jemand die Constraint im SysML-Modell auf ein anderes
      Attribut um, bemerkt das System es nicht. Nachzuziehen in Phase 4.

    * Nur EIN Vergleich pro Anforderung. Zusammengesetzte Constraints
      (and/or, mehrere Grenzen) werden auf den ersten Vergleich reduziert.
      _find_all() warnt, wenn mehr als einer gefunden wird.

    * Der Ausdruck wird nicht ausgewertet, nur seine Bestandteile gelesen.
      Eine Anforderung wie "laenge + breite <= 200" wuerde falsch
      interpretiert. Fuer solche Faelle ist Phase 6 (SMT) vorgesehen.

Die Fixture bleibt als Regressionstest erhalten: sie definiert die erwartete
Zielstruktur unabhaengig von der Verfuegbarkeit des Servers.
=============================================================================
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Requirement
from .sysml_client import SysMLClient
from .units import ureg

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "requirements.json"

COMPARISON_OPERATORS = {"<=", ">=", "<", ">", "=="}

# Felder, die im Modellgraph nach OBEN oder zur Seite zeigen. Wuerde man ihnen
# folgen, waere von jedem Element aus das gesamte Modell erreichbar und die
# Suche nach "dem" Literal einer Anforderung sinnlos.
_UPWARD_FIELDS = frozenset({
    "owner",
    "owningRelationship",
    "owningNamespace",
    "owningType",
    "owningMembership",
    "owningFeatureMembership",
    "membershipOwningNamespace",
    "endOwningType",
    "featuringType",
    "source",
})


# --------------------------------------------------------------------------
# Graphtraversierung
# --------------------------------------------------------------------------

def _refs(element: dict):
    """Alle nach unten gerichteten @id-Referenzen eines Elements."""
    for key, value in element.items():
        if key.startswith("@") or key in _UPWARD_FIELDS:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and set(item) == {"@id"}:
                yield item["@id"]


def reachable(root: dict, by_id: dict[str, dict]) -> list[dict]:
    """Alle von root aus erreichbaren Elemente.

    Bibliothekselemente werden aufgenommen, aber nicht weiter durchlaufen --
    sonst zoege eine einzige Einheit die halbe ISQ-Bibliothek herein.
    """
    out: list[dict] = []
    seen: set[str] = set()
    stack = [root["@id"]]
    while stack:
        eid = stack.pop()
        if eid in seen:
            continue
        seen.add(eid)
        element = by_id.get(eid)
        if element is None:
            continue
        out.append(element)
        if element.get("isLibraryElement"):
            continue
        stack.extend(_refs(element))
    return out


def _find_all(elements: list[dict], predicate, what: str, context: str) -> list[dict]:
    hits = [e for e in elements if predicate(e)]
    if len(hits) > 1:
        print(f"[warn] {context}: {len(hits)} Kandidaten fuer {what}, nehme den ersten")
    return hits


# --------------------------------------------------------------------------
# Umwandlung
# --------------------------------------------------------------------------

def _to_requirement(definition: dict, by_id: dict[str, dict]) -> Requirement | None:
    """Eine RequirementDefinition in das Zwischenformat uebersetzen.

    Gibt None zurueck, wenn eines der drei gesuchten Teile fehlt -- eine
    unvollstaendig extrahierte Anforderung waere gefaehrlicher als gar keine.
    """
    name = definition.get("declaredName") or definition.get("name")
    if not name:
        return None

    subtree = reachable(definition, by_id)

    operators = _find_all(
        subtree,
        lambda e: e.get("operator") in COMPARISON_OPERATORS,
        "Vergleichsoperator", name,
    )
    literals = _find_all(
        subtree,
        lambda e: str(e.get("@type", "")).startswith("Literal") and "value" in e,
        "Grenzwert", name,
    )
    units = _find_all(
        subtree,
        lambda e: e.get("isLibraryElement") and e.get("declaredShortName"),
        "Einheit", name,
    )

    missing = [
        label for label, hits in
        (("Operator", operators), ("Grenzwert", literals), ("Einheit", units))
        if not hits
    ]
    if missing:
        print(f"[warn] {name}: {', '.join(missing)} nicht gefunden -- uebersprungen")
        return None

    unit_symbol = units[0]["declaredShortName"]
    try:
        limit = ureg.Quantity(literals[0]["value"], unit_symbol)
    except Exception as exc:  # pint kennt das Symbol nicht
        print(f"[warn] {name}: Einheit {unit_symbol!r} unbekannt ({exc}) -- uebersprungen")
        return None

    subjects = [
        e.get("declaredName") for e in subtree
        if e.get("@type") == "ReferenceUsage" and e.get("declaredName")
    ]

    return Requirement(
        requirement_id=definition.get("declaredShortName") or name,
        element_id=definition["@id"],
        subject=subjects[0] if subjects else "",
        prop="",  # kommt aus mapping.yaml, siehe Modulkopf
        operator=operators[0]["operator"],
        limit=limit,
        text=name,
    )


def elements_to_requirements(elements: list[dict]) -> list[Requirement]:
    """Reine Funktion -- ohne Netz testbar."""
    by_id = {e["@id"]: e for e in elements if "@id" in e}
    result = []
    for element in elements:
        if element.get("@type") != "RequirementDefinition":
            continue
        if element.get("isLibraryElement"):
            continue
        req = _to_requirement(element, by_id)
        if req:
            result.append(req)
    return result


# --------------------------------------------------------------------------
# Quellen
# --------------------------------------------------------------------------

def from_fixture(path: Path = FIXTURE) -> list[Requirement]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Requirement.from_dict(d) for d in data["requirements"]]


def from_api(project_id: str | None = None, base_url: str | None = None) -> list[Requirement]:
    client = SysMLClient(base_url)
    try:
        if project_id is None:
            projects = client.projects()
            if not projects:
                raise RuntimeError("Keine Projekte im API-Server")
            project_id = sorted(projects, key=lambda p: p.get("created", ""))[-1]["@id"]
        commit_id = client.head_commit(project_id)
        elements = client.all_elements(project_id, commit_id)
    finally:
        client.close()
    return elements_to_requirements(elements)


def load(source: str | None = None) -> list[Requirement]:
    """source="api" liest aus dem Server, sonst aus der Fixture."""
    return from_api() if source == "api" else from_fixture()
