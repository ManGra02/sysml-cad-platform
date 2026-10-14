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

    * Only ONE comparison per requirement. A requirement whose subtree holds
      more than one comparison, literal or unit (and/or, several bounds, an
      offset like `maxLength - 5 [mm]`) is NOT extracted: it is reported as a
      gap, "not checked". It used to collapse to the first comparison with a
      warning on stdout -- which checks one bound of `a >= x and a <= y` and
      reports the whole requirement as passed.

    * The expression is never evaluated, only its parts are read. Something
      like "length + width <= 200" would be misread. That is what SMT over the
      constraint network is for.

What DOES happen now, and did not before: the requirement's SUBJECT is
resolved through the model's own `satisfy` link -- see resolve_satisfies() --
and a definition satisfied by several parts is checked once per part.
A definition that cannot be read is carried as a skip reason, which a run
reports as a gap: a requirement nobody checked must not vanish from the report.
=============================================================================
"""

from __future__ import annotations

from collections import deque

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
) -> dict[str, list[tuple[dict, list[str]]]]:
    """Map RequirementDefinition id -> [(satisfying PartUsage, link path), ...].

    A list, because one definition is routinely satisfied by several parts --
    `MaxMass` for every component, the bore radius for both sides of an
    interface. Keeping only one of them used to drop the others silently: the
    last `satisfy` in the payload won, and the part named by the earlier ones
    was never checked and never reported. One entry per distinct part, in the
    order the model states them.

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
    out: dict[str, list[tuple[dict, list[str]]]] = {}

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

        links = out.setdefault(definition["@id"], [])
        # Two usages of one definition satisfied by the same part are one check.
        if all(known["@id"] != part["@id"] for known, _ in links):
            links.append((part, [satisfy["@id"]] + definition_path + part_path))

    return out


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def _to_requirements(
    definition: dict,
    by_id: dict[str, dict],
    satisfied_by: dict[str, list[tuple[dict, list[str]]]] | None = None,
) -> tuple[list[Requirement], str | None]:
    """Translate one RequirementDefinition into the intermediate format.

    Returns the requirements -- one per satisfying part, or one with the
    definition's own subject parameter when nothing satisfies it -- or, when
    the definition cannot be read, no requirements and the reason. A partially
    extracted requirement would be more dangerous than none at all, and "none"
    has to be visible: the caller reports the reason as a gap.
    """
    name = definition.get("declaredName") or definition.get("name")
    if not name:
        return [], None
    requirement_id = definition.get("declaredShortName") or name

    subtree = reachable(definition, by_id)

    found = {
        "comparison": [e for e in subtree if e.get("operator") in COMPARISON_OPERATORS],
        "limit": [
            e for e in subtree
            if str(e.get("@type", "")).startswith("Literal") and "value" in e
        ],
        "unit": [
            e for e in subtree
            if e.get("isLibraryElement") and e.get("declaredShortName")
        ],
    }

    missing = [label for label, hits in found.items() if not hits]
    if missing:
        return [], f"{requirement_id}: not extracted -- no {', '.join(missing)} found"

    # One of each or nothing. The first of two comparisons is one bound of a
    # compound constraint, and the first of two literals may be an offset
    # rather than the limit: checking either would report a pass for a
    # requirement that was only half read.
    several = [f"{len(hits)} {label}s" for label, hits in found.items() if len(hits) > 1]
    if several:
        return [], (
            f"{requirement_id}: not extracted -- {', '.join(several)}; compound "
            f"constraints are not supported yet (see extract.py)"
        )

    unit_symbol = found["unit"][0]["declaredShortName"]
    try:
        limit = ureg.Quantity(found["limit"][0]["value"], unit_symbol)
    except Exception as exc:  # pint does not know the symbol
        return [], f"{requirement_id}: not extracted -- unknown unit {unit_symbol!r} ({exc})"

    # Preferred: the parts the model says satisfy this requirement. Fallback:
    # the subject parameter of the definition, which is what a model without a
    # satisfy link can offer.
    subjects = [
        (part.get("declaredName") or part.get("declaredShortName") or "", part["@id"])
        for part, _path in (satisfied_by or {}).get(definition["@id"], [])
    ]
    if not subjects:
        parameters = [
            e.get("declaredName") for e in subtree
            if e.get("@type") == "ReferenceUsage" and e.get("declaredName")
        ]
        subjects = [(parameters[0] if parameters else "", "")]

    return [
        Requirement(
            requirement_id=requirement_id,
            element_id=definition["@id"],
            subject=subject,
            subject_id=subject_id,
            prop="",  # comes from mapping.yaml, see module header
            operator=found["comparison"][0]["operator"],
            limit=limit,
            text=name,
        )
        for subject, subject_id in subjects
    ], None


def extract(elements: list[dict]) -> tuple[list[Requirement], list[str]]:
    """Every requirement in the payload, plus a reason for each definition that
    could not be read. Pure function -- testable without a network."""
    by_id = {e["@id"]: e for e in elements if "@id" in e}
    satisfied_by = resolve_satisfies(elements, by_id)
    requirements: list[Requirement] = []
    skipped: list[str] = []
    for element in elements:
        if element.get("@type") != "RequirementDefinition":
            continue
        if element.get("isLibraryElement"):
            continue
        found, reason = _to_requirements(element, by_id, satisfied_by)
        requirements.extend(found)
        if reason:
            skipped.append(reason)
    return requirements, skipped


def elements_to_requirements(elements: list[dict]) -> list[Requirement]:
    """The requirements alone, for callers that do not report coverage."""
    return extract(elements)[0]


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

def from_capture(project: Project) -> list[Requirement]:
    """Requirements from the project's offline capture -- the real extractor
    over a real API response, with no server in the room."""
    return elements_to_requirements(project.elements())


def fetch_elements(
    project_name: str,
    base_url: str | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """Every element of the server project NAMED `project_name`, at its head
    commit, plus the ids of that model state.

    By name: it used to be "whichever was published most recently", which
    meant that publishing a second model silently changed what `verify api`
    verified. Which model is checked is stated by the project, never inferred
    from a timestamp -- see `SysMLClient.project_named`.

    SRS FREQ-1 requires the commit id to be recorded so that every later result
    can be attributed to an exact state of the system model. Fetching it and
    dropping it, as this used to, makes a verdict unciteable.
    """
    client = SysMLClient(base_url)
    try:
        project_id = client.project_named(project_name)["@id"]
        commit_id = client.head_commit(project_id)
        elements = client.all_elements(project_id, commit_id)
    finally:
        client.close()
    return elements, {"sysml_project_id": project_id, "sysml_commit_id": commit_id}


def load(project: Project, source: str | None = None) -> list[Requirement]:
    """source="api" reads from the server, anything else from the capture."""
    return load_with_context(project, source)[0]


def load_with_context(
    project: Project,
    source: str | None = None,
) -> tuple[list[Requirement], list[str], dict[str, str]]:
    """Requirements, the definitions that could not be read, and the model
    state they came from (empty for a capture)."""
    if source == "api":
        elements, state = fetch_elements(project.sysml_project)
    else:
        elements, state = project.elements(), {}
    requirements, skipped = extract(elements)
    return requirements, skipped, state
