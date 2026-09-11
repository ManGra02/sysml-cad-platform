"""Requirement extraction from the SysML v2 API.

=============================================================================
DELIBERATE SIMPLIFICATIONS
=============================================================================
This extractor does not read the full metamodel. Within the subgraph reachable
from a RequirementDefinition it looks for three things:

    1. OPERATOR  -- the first OperatorExpression carrying a comparison
                    (<=, >=, <, >, ==). Here that is the ConstraintUsage below
                    the RequirementConstraintMembership.
    2. LIMIT     -- the first literal (LiteralInteger / LiteralRational) with a
                    "value" field: the 120 or the 0.9 from the AttributeUsage
                    maxLength / maxMass.
    3. UNIT      -- the first AttributeUsage with isLibraryElement=true and a
                    declaredShortName ("mm", "kg"). Units are not a field in
                    the model; `120 [mm]` is an OperatorExpression with
                    operator="[" whose second operand points at the unit
                    element of the standard library.

What still does NOT happen, and why:

    * The measured ATTRIBUTE (length, mass) is not parsed out of
      "housing.length <= maxLength". It comes from mapping.yaml.
      COST: retarget the constraint to a different attribute in SysML and the
      system does not notice. Closing this needs the FeatureChainExpression
      resolved; it is the next extractor step.

    * Only ONE comparison per requirement. Compound constraints (and/or,
      several bounds) collapse to the first comparison; _find_all() warns.

    * The expression is never evaluated, only its parts are read. Something
      like "length + width <= 200" would be misread. That is what SMT over the
      constraint network is for.

What DOES happen now, and did not before: the requirement's SUBJECT is
resolved through the model's own `satisfy` link -- see resolve_satisfies().
=============================================================================
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from .model import Requirement
from .project import Project
from .sysml_client import SysMLClient
from .units import ureg

COMPARISON_OPERATORS = {"<=", ">=", "<", ">", "=="}

# Fields pointing UP or sideways in the model graph. Following them would make
# the whole model reachable from any node, and the search for "the" literal of
# one requirement meaningless.
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
# Graph traversal
# --------------------------------------------------------------------------

def _refs(element: dict):
    """Every downward @id reference of an element."""
    for key, value in element.items():
        if key.startswith("@") or key in _UPWARD_FIELDS:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and set(item) == {"@id"}:
                yield item["@id"]


def reachable(root: dict, by_id: dict[str, dict]) -> list[dict]:
    """Everything reachable from root.

    Library elements are collected but not expanded -- otherwise a single unit
    would drag in half of the ISQ library.
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


def find_first(
    root: dict,
    by_id: dict[str, dict],
    predicate,
    max_depth: int = 12,
) -> tuple[dict | None, list[str]]:
    """Breadth-first search downward from root for the nearest match.

    Returns the element and the path of element ids that led to it. The path is
    not decoration: change-impact analysis has to be able to say *why* it
    thinks two elements are related, and this is where that evidence comes
    from.
    """
    queue = deque([(root["@id"], [root["@id"]])])
    seen = {root["@id"]}
    while queue:
        eid, path = queue.popleft()
        element = by_id.get(eid)
        if element is None:
            continue
        if eid != root["@id"] and predicate(element):
            return element, path
        if element.get("isLibraryElement") or len(path) > max_depth:
            continue
        for ref in _refs(element):
            if ref not in seen:
                seen.add(ref)
                queue.append((ref, path + [ref]))
    return None, []


def _of_type(type_name: str):
    return lambda e: e.get("@type") == type_name


# --------------------------------------------------------------------------
# The satisfy link
# --------------------------------------------------------------------------

def _chained_subject(branch: dict, by_id: dict[str, dict]) -> tuple[dict | None, list[str]]:
    """The part named by a dotted path, e.g. `satisfy c by gearbox.housing`.

    A plain `by gearbox` serialises as a Membership pointing straight at the
    PartUsage. A dotted path does not: it becomes an anonymous Feature owning one
    FeatureChaining per segment, in order.

        Feature
          |- FeatureChaining.chainingFeature -> PartUsage[gearbox]   first
          `- FeatureChaining.chainingFeature -> PartUsage[housing]   LAST = meant

    The last link is the subject; every earlier one is the road to it. Nearest-
    match search finds `gearbox` and is wrong in the worst way -- it measures the
    assembly where the requirement is about one component, and reports a
    confident verdict for the wrong object.

    Order comes from the order of `ownedRelationship`, which is the only thing
    the payload offers -- there is no index field on FeatureChaining. If the last
    link does not resolve to a usage, this returns None and the caller falls
    back rather than guessing at a different link.
    """
    def owns_a_chain(element: dict) -> bool:
        return any(
            by_id.get(rel.get("@id", ""), {}).get("@type") == "FeatureChaining"
            for rel in element.get("ownedRelationship") or []
        )

    feature, path = find_first(branch, by_id, owns_a_chain)
    if feature is None:
        return None, []

    chain = [
        by_id[rel["@id"]]
        for rel in feature.get("ownedRelationship") or []
        if by_id.get(rel.get("@id", ""), {}).get("@type") == "FeatureChaining"
    ]
    if not chain:
        return None, []

    last = by_id.get((chain[-1].get("chainingFeature") or {}).get("@id", ""))
    if last is None or not str(last.get("@type", "")).endswith("Usage"):
        return None, []
    return last, path + [chain[-1]["@id"], last["@id"]]


def resolve_satisfies(
    elements: list[dict],
    by_id: dict[str, dict] | None = None,
) -> dict[str, tuple[dict, list[str]]]:
    """Map RequirementDefinition id -> (satisfying PartUsage, link path).

    `satisfy maxLengthCheck by motorHousing;` lands in the model as a
    SatisfyRequirementUsage with two branches:

        ReferenceSubsetting.general -> RequirementUsage
                                       -> FeatureTyping.general -> RequirementDefinition
        SubjectMembership.memberElement -> ReferenceUsage
                                       -> FeatureValue -> FeatureReferenceExpression
                                       -> Membership.memberElement -> PartUsage

    This link, not mapping.yaml, is what says which physical thing a
    requirement is about. Reading it is what lets the mapping be anchored on
    parts instead of on requirements: a new requirement on an already-mapped
    part then needs no new mapping entry at all.

    The two branches are searched separately on purpose. Searching the whole
    SatisfyRequirementUsage at once would work today but would start crossing
    between neighbouring requirements as soon as a model has more than one
    part per satisfy.
    """
    by_id = by_id or {e["@id"]: e for e in elements if "@id" in e}
    out: dict[str, tuple[dict, list[str]]] = {}

    for satisfy in elements:
        if satisfy.get("@type") != "SatisfyRequirementUsage":
            continue

        definition = part = None
        definition_path: list[str] = []
        part_path: list[str] = []

        for ref in satisfy.get("ownedRelationship", []):
            branch = by_id.get(ref.get("@id", ""))
            if branch is None:
                continue
            if branch["@type"] == "ReferenceSubsetting":
                definition, definition_path = find_first(
                    branch, by_id, _of_type("RequirementDefinition")
                )
            elif branch["@type"] == "SubjectMembership":
                # A dotted path first: `by gearbox.housing` must resolve to
                # housing, and the nearest PartUsage under it is gearbox.
                part, part_path = _chained_subject(branch, by_id)
                if part is None:
                    part, part_path = find_first(branch, by_id, _of_type("PartUsage"))

        if definition is None or part is None:
            continue

        path = [satisfy["@id"]] + definition_path + part_path
        out[definition["@id"]] = (part, path)

    return out


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def _find_all(elements: list[dict], predicate, what: str, context: str) -> list[dict]:
    hits = [e for e in elements if predicate(e)]
    if len(hits) > 1:
        print(f"[warn] {context}: {len(hits)} candidates for {what}, taking the first")
    return hits


def _to_requirement(
    definition: dict,
    by_id: dict[str, dict],
    satisfied_by: dict[str, tuple[dict, list[str]]] | None = None,
) -> Requirement | None:
    """Translate one RequirementDefinition into the intermediate format.

    Returns None if any of the three parts is missing -- a partially extracted
    requirement would be more dangerous than none at all.
    """
    name = definition.get("declaredName") or definition.get("name")
    if not name:
        return None

    subtree = reachable(definition, by_id)

    operators = _find_all(
        subtree,
        lambda e: e.get("operator") in COMPARISON_OPERATORS,
        "comparison operator", name,
    )
    literals = _find_all(
        subtree,
        lambda e: str(e.get("@type", "")).startswith("Literal") and "value" in e,
        "limit value", name,
    )
    units = _find_all(
        subtree,
        lambda e: e.get("isLibraryElement") and e.get("declaredShortName"),
        "unit", name,
    )

    missing = [
        label for label, hits in
        (("operator", operators), ("limit", literals), ("unit", units))
        if not hits
    ]
    if missing:
        print(f"[warn] {name}: {', '.join(missing)} not found -- skipped")
        return None

    unit_symbol = units[0]["declaredShortName"]
    try:
        limit = ureg.Quantity(literals[0]["value"], unit_symbol)
    except Exception as exc:  # pint does not know the symbol
        print(f"[warn] {name}: unknown unit {unit_symbol!r} ({exc}) -- skipped")
        return None

    # Preferred: the part the model says satisfies this requirement. Fallback:
    # the subject parameter of the definition, which is what a model without a
    # satisfy link can offer.
    satisfied = (satisfied_by or {}).get(definition["@id"])
    if satisfied is not None:
        part, _path = satisfied
        subject = part.get("declaredName") or part.get("declaredShortName") or ""
        subject_id = part["@id"]
    else:
        parameters = [
            e.get("declaredName") for e in subtree
            if e.get("@type") == "ReferenceUsage" and e.get("declaredName")
        ]
        subject = parameters[0] if parameters else ""
        subject_id = ""

    return Requirement(
        requirement_id=definition.get("declaredShortName") or name,
        element_id=definition["@id"],
        subject=subject,
        subject_id=subject_id,
        prop="",  # comes from mapping.yaml, see module header
        operator=operators[0]["operator"],
        limit=limit,
        text=name,
    )


def elements_to_requirements(elements: list[dict]) -> list[Requirement]:
    """Pure function -- testable without a network."""
    by_id = {e["@id"]: e for e in elements if "@id" in e}
    satisfied_by = resolve_satisfies(elements, by_id)
    result = []
    for element in elements:
        if element.get("@type") != "RequirementDefinition":
            continue
        if element.get("isLibraryElement"):
            continue
        req = _to_requirement(element, by_id, satisfied_by)
        if req:
            result.append(req)
    return result


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

def from_capture(project: Project) -> list[Requirement]:
    """Requirements from the project's offline capture -- the real extractor
    over a real API response, with no server in the room."""
    return elements_to_requirements(project.elements())


def from_api(
    project_name: str,
    base_url: str | None = None,
) -> tuple[list[Requirement], dict[str, str]]:
    """Requirements plus the model state they came from.

    The server project is found BY NAME. It used to be "whichever was published
    most recently", which meant that publishing a second model silently changed
    what `verify api` verified. Which model is checked is stated by the project,
    never inferred from a timestamp.

    SRS FREQ-1 requires the commit id to be recorded so that every later result
    can be attributed to an exact state of the system model. Fetching it and
    dropping it, as this used to, makes a verdict unciteable.
    """
    client = SysMLClient(base_url)
    try:
        projects = client.projects()
        matching = [p for p in projects if p.get("name") == project_name]
        if not matching:
            available = ", ".join(sorted(p.get("name", "?") for p in projects)) or "none"
            raise RuntimeError(
                f"no project named {project_name!r} on the API server. "
                f"Available: {available}"
            )
        if len(matching) > 1:
            # Publishing the same package twice leaves two projects with one
            # name. Take the newest of THOSE -- same-named, so the same model --
            # and say so, because a silent choice here is a silent choice of
            # commit.
            matching.sort(key=lambda p: p.get("created", ""))
            print(f"[warn] {len(matching)} server projects named {project_name!r}; "
                  f"using the most recently created")
        project_id = matching[-1]["@id"]
        commit_id = client.head_commit(project_id)
        elements = client.all_elements(project_id, commit_id)
    finally:
        client.close()
    return elements_to_requirements(elements), {
        "sysml_project_id": project_id,
        "sysml_commit_id": commit_id,
    }


def load(project: Project, source: str | None = None) -> list[Requirement]:
    """source="api" reads from the server, anything else from the capture."""
    return load_with_context(project, source)[0]


def load_with_context(
    project: Project,
    source: str | None = None,
) -> tuple[list[Requirement], dict[str, str]]:
    if source == "api":
        return from_api(project.sysml_project)
    return from_capture(project), {}
