"""Translate raw SysML v2 API JSON (a list of elements) into the common ModelSnapshot.

Works on the output of GET /projects/{p}/commits/{c}/elements, and equally on a commit
payload file ({"change": [{"identity":..., "payload":...}]}) so it can be tested offline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from . import units
from .expressions import EvalResult, ExpressionEvaluator, ref_id, ref_ids
from .models import Attribute, ModelElement, ModelSnapshot, Relation

# SysML @type -> neutral kind. Anything not listed is internal structure (memberships, features,
# expressions, ...) and does not become a ModelElement.
KIND_BY_TYPE = {
    "Package": "package", "LibraryPackage": "package", "Namespace": "package",
    "PartUsage": "part", "PartDefinition": "part_def",
    "ItemUsage": "item", "ItemDefinition": "item_def",
    "PortUsage": "port", "PortDefinition": "port_def",
    "InterfaceUsage": "interface", "InterfaceDefinition": "interface_def",
    "ConnectionUsage": "connection", "ConnectionDefinition": "connection_def", "BindingConnectorAsUsage": "connection",
    "FlowConnectionUsage": "connection", "SuccessionFlowConnectionUsage": "connection",
    "RequirementUsage": "requirement", "RequirementDefinition": "requirement_def",
    "SatisfyRequirementUsage": "satisfy",
    "ConstraintUsage": "constraint", "ConstraintDefinition": "constraint_def", "AssertConstraintUsage": "constraint",
    "VerificationCaseUsage": "verification", "VerificationCaseDefinition": "verification_def",
    "AllocationUsage": "allocation", "AllocationDefinition": "allocation_def",
    "ActionUsage": "action", "ActionDefinition": "action_def",
    "EnumerationDefinition": "enum_def", "AttributeDefinition": "attribute_def",
}
DEFINITION_KINDS = {k for k in KIND_BY_TYPE.values() if k.endswith("_def")}


def normalise_elements(data: Any) -> list[dict]:
    """Accept an element list, a commit payload ({"change": [...]}) or {"elements": [...]}."""
    if isinstance(data, dict) and "change" in data:
        out = []
        for ch in data["change"]:
            p = dict(ch.get("payload") or {})
            if not p:
                continue
            p.setdefault("@id", ref_id(ch.get("identity")) or p.get("elementId"))
            out.append(p)
        return out
    if isinstance(data, dict) and "elements" in data:
        data = data["elements"]
    out = []
    for el in data or []:
        e = dict(el)
        e.setdefault("@id", e.get("elementId") or e.get("identity", {}).get("@id"))
        out.append(e)
    return out


class SysMLParser:
    def __init__(self, raw_elements: Iterable[dict], include_library: bool = False):
        self.raw = normalise_elements(list(raw_elements) if not isinstance(raw_elements, dict) else raw_elements)
        self.els: dict[str, dict] = {e["@id"]: e for e in self.raw if e.get("@id")}
        self.include_library = include_library
        self.warnings: list[str] = []

        # element id -> short name from any Membership that points at it (units are often
        # library elements that are NOT in the project, but memberships still carry their names)
        self.unit_names: dict[str, str] = {}
        for e in self.els.values():
            if "Membership" in e.get("@type", "") or e.get("@type") == "FeatureValue":
                target = e.get("memberElementId") or ref_id(e.get("memberElement"))
                nm = e.get("memberShortName") or e.get("memberName")
                if target and nm and target not in self.unit_names:
                    self.unit_names[target] = nm
        for eid, e in self.els.items():
            if e.get("shortName") or e.get("declaredShortName"):
                self.unit_names.setdefault(eid, e.get("declaredShortName") or e.get("shortName"))

        # FeatureValue lookup: feature id -> value expression id
        self.value_expr: dict[str, str] = {}
        for e in self.els.values():
            if e.get("@type") == "FeatureValue":
                f = ref_id(e.get("featureWithValue")) or ref_id(e.get("owningRelatedElement"))
                v = ref_id(e.get("value")) or ref_id(e.get("ownedMemberElement")) or e.get("memberElementId")
                if f and v:
                    self.value_expr[f] = v

        self._value_cache: dict[str, EvalResult | None] = {}
        self._evaluating: set[str] = set()
        self.evaluator = ExpressionEvaluator(self.els, self.unit_names, value_of_feature=self.feature_value)

    # ------------------------------------------------------------------ basics
    @staticmethod
    def name(el: dict) -> str:
        return el.get("declaredName") or el.get("name") or el.get("declaredShortName") or el.get("shortName") or ""

    def owner_of(self, el: dict) -> str | None:
        for key in ("owner", "owningType", "owningNamespace", "owningRelatedElement", "owningDefinition", "owningUsage"):
            o = ref_id(el.get(key))
            if o:
                return o
        return None

    def is_skipped(self, el: dict) -> bool:
        return (not self.include_library and bool(el.get("isLibraryElement"))) or bool(el.get("isImplied"))

    def structural_parent(self, el: dict, structural_ids: set[str]) -> str | None:
        seen = set()
        cur = self.owner_of(el)
        while cur and cur not in seen:
            if cur in structural_ids:
                return cur
            seen.add(cur)
            parent_el = self.els.get(cur)
            cur = self.owner_of(parent_el) if parent_el else None
        return None

    def feature_value(self, feature_id: str) -> EvalResult | None:
        """Value of a feature (attribute) as EvalResult, with recursion guard."""
        if feature_id in self._value_cache:
            return self._value_cache[feature_id]
        expr = self.value_expr.get(feature_id)
        if not expr or feature_id in self._evaluating:
            return None
        self._evaluating.add(feature_id)
        try:
            r = self.evaluator.evaluate(expr)
        finally:
            self._evaluating.discard(feature_id)
        self._value_cache[feature_id] = r
        return r

    def doc_text(self, eid: str) -> str | None:
        texts = []
        for e in self.els.values():
            if e.get("@type") in ("Documentation", "Comment") and (
                    ref_id(e.get("owner")) == eid or eid in ref_ids(e.get("annotatedElement"))):
                if e.get("body"):
                    texts.append(e["body"].strip().strip("/*").strip())
        return "\n".join(texts) or None

    # ------------------------------------------------------------------ main
    def parse(self, project_id: str = "", version: str = "", branch_id: str | None = None) -> ModelSnapshot:
        structural = {eid: e for eid, e in self.els.items()
                      if e.get("@type") in KIND_BY_TYPE and not self.is_skipped(e)}
        sids = set(structural)

        elements: list[ModelElement] = []
        for eid, e in structural.items():
            kind = KIND_BY_TYPE[e["@type"]]
            extra: dict[str, Any] = {}
            if kind in ("requirement", "requirement_def"):
                extra["req_id"] = e.get("reqId") or e.get("declaredShortName")
                text = e.get("text")
                if isinstance(text, list):
                    text = "\n".join(str(t) for t in text)
                extra["text"] = text or self.doc_text(eid)
            if e.get("multiplicity"):
                extra["multiplicity_id"] = ref_id(e.get("multiplicity"))
            elements.append(ModelElement(
                id=eid, name=self.name(e) or f"<{e['@type']}>", kind=kind, native_type=e["@type"],
                qualified_name=e.get("qualifiedName") or "", parent_id=self.structural_parent(e, sids),
                type_ids=[] if kind in DEFINITION_KINDS else (ref_ids(e.get("definition")) or ref_ids(e.get("type"))),
                short_name=e.get("declaredShortName") or e.get("shortName"), doc=self.doc_text(eid),
                is_definition=kind in DEFINITION_KINDS, extra=extra,
            ))

        attributes: list[Attribute] = []
        for eid, e in self.els.items():
            if e.get("@type") != "AttributeUsage" or self.is_skipped(e):
                continue
            owner = self.structural_parent(e, sids)
            if owner is None:
                continue
            a = Attribute(id=eid, owner_id=owner, name=self.name(e))
            r = self.feature_value(eid)
            if r is not None:
                a.value, a.unit, a.expression, a.value_element_id = r.value, r.unit, r.text, r.literal_id
                a.warnings.extend(r.warnings)
                a.value_si, a.unit_si = units.to_si(r.value, r.unit)
                if r.unit and a.value_si is None and isinstance(r.value, (int, float)):
                    a.warnings.append(f"unknown unit '{r.unit}', not normalised")
            attributes.append(a)

        relations = self._relations(sids)

        return ModelSnapshot(
            source="sysml", project_id=project_id, version=version, branch_id=branch_id,
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            elements=sorted(elements, key=lambda x: x.qualified_name or x.name),
            attributes=attributes, relations=relations, warnings=self.warnings,
        )

    def _relations(self, sids: set[str]) -> list[Relation]:
        rels: list[Relation] = []
        for eid, e in self.els.items():
            if self.is_skipped(e):
                continue
            t = e.get("@type")
            if t in ("FeatureTyping",):
                s, g = ref_id(e.get("typedFeature")), ref_id(e.get("type"))
                if s in sids and g:
                    rels.append(Relation(s, g, "typed_by", eid))
            elif t == "Redefinition":
                s, g = ref_id(e.get("redefiningFeature")), ref_id(e.get("redefinedFeature"))
                if s and g and (s in sids or s in self.value_expr or self.els.get(s, {}).get("@type") == "AttributeUsage"):
                    rels.append(Relation(s, g, "redefines", eid))
            elif t == "SatisfyRequirementUsage":
                req = ref_id(e.get("satisfiedRequirement")) or ref_id(e.get("requirementDefinition"))
                by = ref_id(e.get("satisfyingFeature"))
                if req and by:
                    rels.append(Relation(by, req, "satisfies", eid))
            elif t in ("ConnectionUsage", "InterfaceUsage", "BindingConnectorAsUsage", "FlowConnectionUsage", "AllocationUsage"):
                ends = ref_ids(e.get("relatedFeature")) or ref_ids(e.get("connectorEnd"))
                src, tgt = ref_id(e.get("sourceFeature")), ref_ids(e.get("targetFeature"))
                pairs = [(src, x) for x in tgt] if src and tgt else list(zip(ends, ends[1:]))
                kind = "allocates" if t == "AllocationUsage" else "connects"
                for a, b in pairs:
                    if a and b:
                        rels.append(Relation(a, b, kind, eid))
        # typed_by also from usage.definition if no FeatureTyping elements were exported
        have = {(r.source_id, r.target_id) for r in rels if r.kind == "typed_by"}
        for eid in sids:
            for d in ref_ids(self.els[eid].get("definition")):
                if (eid, d) not in have and d in self.els:
                    rels.append(Relation(eid, d, "typed_by"))
        return rels


def parse_elements(raw: Any, project_id: str = "", version: str = "", branch_id: str | None = None,
                   include_library: bool = False) -> ModelSnapshot:
    return SysMLParser(raw, include_library=include_library).parse(project_id, version, branch_id)
