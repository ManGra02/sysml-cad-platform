"""Requirement extraction from raw SysML v2 elements (``SysmlService.raw_elements``).

Works on the FULL metamodel, as the SysML v2 Pilot publishes it (FeatureMembership,
RequirementDefinition, constraint expressions, library units). The platform's
simplified demo models (``ModelBuilder``) carry none of that and yield no requirements.

DELIBERATE SIMPLIFICATIONS. Within the subgraph reachable from a RequirementDefinition
it looks for exactly three things:

    1. OPERATOR  -- the OperatorExpression carrying a comparison (<=, >=, <, >, ==)
    2. LIMIT     -- the literal (LiteralInteger / LiteralRational) with a "value"
    3. UNIT      -- the library AttributeUsage with a declaredShortName ("mm", "kg");
                    ``120 [mm]`` is an OperatorExpression "[" whose second operand
                    points at the unit element of the standard library

* The measured ATTRIBUTE is not parsed out of "housing.length <= maxLength"; it comes
  from the mapping. Retarget the constraint in SysML and this does not notice.
* Only ONE comparison per requirement. More than one comparison, literal or unit
  (and/or, two bounds, an offset) is not extracted but reported as a gap -- checking
  one bound of ``a >= x and a <= y`` would report the whole requirement as passed.
* The expression is never evaluated, only its parts are read.

The SUBJECT is resolved through the model's own ``satisfy`` link (resolve_satisfies);
a definition satisfied by several parts is checked once per part.
"""

from __future__ import annotations

from collections import deque

from app.projects.bds.model import Requirement
from app.projects.bds.units import ureg

COMPARISON_OPERATORS = {"<=", ">=", "<", ">", "=="}

#: Fields pointing UP or sideways in the model graph. Following them would make the
#: whole model reachable from any node.
_UPWARD_FIELDS = frozenset({
    "owner", "owningRelationship", "owningNamespace", "owningType", "owningMembership",
    "owningFeatureMembership", "membershipOwningNamespace", "endOwningType",
    "featuringType", "source",
})


def _refs(element):
    """Every downward @id reference of an element."""
    for key, value in element.items():
        if key.startswith("@") or key in _UPWARD_FIELDS:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and set(item) == {"@id"}:
                yield item["@id"]


def reachable(root, by_id):
    """Everything reachable from root. Library elements are collected but not
    expanded -- a single unit would otherwise drag in half of the ISQ library."""
    out, seen, stack = [], set(), [root["@id"]]
    while stack:
        eid = stack.pop()
        if eid in seen:
            continue
        seen.add(eid)
        element = by_id.get(eid)
        if element is None:
            continue
        out.append(element)
        if not element.get("isLibraryElement"):
            stack.extend(_refs(element))
    return out


def find_first(root, by_id, predicate, max_depth=12):
    """Breadth-first search downward for the nearest match -> (element, id path)."""
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


def of_type(type_name):
    return lambda e: e.get("@type") == type_name


def _chained_subject(branch, by_id):
    """The part named by a dotted path, e.g. ``satisfy c by gearbox.housing``.

    A dotted path becomes an anonymous Feature owning one FeatureChaining per segment,
    in ``ownedRelationship`` order; the LAST link is the subject. Nearest-match search
    would find ``gearbox`` and measure the assembly where the requirement is about one
    component.
    """
    def owns_a_chain(element):
        return any(by_id.get(rel.get("@id", ""), {}).get("@type") == "FeatureChaining"
                   for rel in element.get("ownedRelationship") or [])

    feature, path = find_first(branch, by_id, owns_a_chain)
    if feature is None:
        return None, []
    chain = [by_id[rel["@id"]] for rel in feature.get("ownedRelationship") or []
             if by_id.get(rel.get("@id", ""), {}).get("@type") == "FeatureChaining"]
    if not chain:
        return None, []
    last = by_id.get((chain[-1].get("chainingFeature") or {}).get("@id", ""))
    if last is None or not str(last.get("@type", "")).endswith("Usage"):
        return None, []
    return last, path + [chain[-1]["@id"], last["@id"]]


def resolve_satisfies(elements, by_id=None):
    """RequirementDefinition id -> [(satisfying PartUsage, link path), ...].

    ``satisfy maxLengthCheck by motorHousing;`` is a SatisfyRequirementUsage with two
    branches, searched separately so neighbouring requirements never cross:

        ReferenceSubsetting.general -> RequirementUsage -> FeatureTyping -> RequirementDefinition
        SubjectMembership -> ReferenceUsage -> FeatureValue -> FeatureReferenceExpression
                          -> Membership.memberElement -> PartUsage
    """
    by_id = by_id or {e["@id"]: e for e in elements if "@id" in e}
    out = {}
    for satisfy in elements:
        if satisfy.get("@type") != "SatisfyRequirementUsage":
            continue
        definition = part = None
        definition_path, part_path = [], []
        for ref in satisfy.get("ownedRelationship", []):
            branch = by_id.get(ref.get("@id", ""))
            if branch is None:
                continue
            if branch["@type"] == "ReferenceSubsetting":
                definition, definition_path = find_first(branch, by_id, of_type("RequirementDefinition"))
            elif branch["@type"] == "SubjectMembership":
                part, part_path = _chained_subject(branch, by_id)
                if part is None:
                    part, part_path = find_first(branch, by_id, of_type("PartUsage"))
        if definition is None or part is None:
            continue
        links = out.setdefault(definition["@id"], [])
        if all(known["@id"] != part["@id"] for known, _ in links):
            links.append((part, [satisfy["@id"]] + definition_path + part_path))
    return out


def _to_requirements(definition, by_id, satisfied_by=None):
    """One RequirementDefinition -> (requirements, skip reason or None).

    One requirement per satisfying part, or one with the definition's own subject
    parameter when nothing satisfies it. A partially extracted requirement would be
    more dangerous than none, and "none" has to be visible.
    """
    name = definition.get("declaredName") or definition.get("name")
    if not name:
        return [], None
    requirement_id = definition.get("declaredShortName") or name
    subtree = reachable(definition, by_id)

    found = {
        "comparison": [e for e in subtree if e.get("operator") in COMPARISON_OPERATORS],
        "limit": [e for e in subtree if str(e.get("@type", "")).startswith("Literal") and "value" in e],
        "unit": [e for e in subtree if e.get("isLibraryElement") and e.get("declaredShortName")],
    }
    missing = [label for label, hits in found.items() if not hits]
    if missing:
        return [], "%s: not extracted -- no %s found" % (requirement_id, ", ".join(missing))
    several = ["%d %ss" % (len(hits), label) for label, hits in found.items() if len(hits) > 1]
    if several:
        return [], ("%s: not extracted -- %s; compound constraints are not supported"
                    % (requirement_id, ", ".join(several)))

    unit_symbol = found["unit"][0]["declaredShortName"]
    try:
        limit = ureg.Quantity(found["limit"][0]["value"], unit_symbol)
    except Exception as exc:   # pint does not know the symbol
        return [], "%s: not extracted -- unknown unit %r (%s)" % (requirement_id, unit_symbol, exc)

    subjects = [(part.get("declaredName") or part.get("declaredShortName") or "", part["@id"])
                for part, _path in (satisfied_by or {}).get(definition["@id"], [])]
    if not subjects:
        parameters = [e.get("declaredName") for e in subtree
                      if e.get("@type") == "ReferenceUsage" and e.get("declaredName")]
        subjects = [(parameters[0] if parameters else "", "")]

    return [
        Requirement(requirement_id=requirement_id, element_id=definition["@id"], subject=subject,
                    subject_id=subject_id, prop="", operator=found["comparison"][0]["operator"],
                    limit=limit, text=name)
        for subject, subject_id in subjects
    ], None


def extract(elements):
    """-> (requirements, skip reasons). Pure function -- testable without a network."""
    by_id = {e["@id"]: e for e in elements if "@id" in e}
    satisfied_by = resolve_satisfies(elements, by_id)
    requirements, skipped = [], []
    for element in elements:
        if element.get("@type") != "RequirementDefinition" or element.get("isLibraryElement"):
            continue
        found, reason = _to_requirements(element, by_id, satisfied_by)
        requirements.extend(found)
        if reason:
            skipped.append(reason)
    return requirements, skipped


def leaf(name):
    """Last segment of a qualified name: MotorHousing::motorHousing -> motorHousing."""
    return name.rsplit("::", 1)[-1]


def by_key(requirements):
    """{(requirement_id, part): requirement} -- the key gates and mapping entries use."""
    return {(r.requirement_id, leaf(r.subject)): r for r in requirements}
