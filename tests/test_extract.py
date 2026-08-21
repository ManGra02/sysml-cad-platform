"""Prueft die Graphtraversierung gegen die reale API-Struktur.

Der Elementgraph unten ist aus einem echten %publish-Dump nachgebaut:
RequirementDefinition -> FeatureMembership -> AttributeUsage[maxLength]
-> FeatureValue -> OperatorExpression("[") -> {LiteralInteger, Einheit},
plus RequirementConstraintMembership -> ConstraintUsage -> "<=".
"""

from sysmlcad.extract import elements_to_requirements


def _graph(name, value, unit_short, operator="<="):
    p = name.lower()
    return [
        {"@id": f"{p}-req", "@type": "RequirementDefinition", "declaredName": name,
         "ownedRelationship": [{"@id": f"{p}-fm"}, {"@id": f"{p}-rcm"},
                               {"@id": f"{p}-sm"}]},
        # Subject
        {"@id": f"{p}-sm", "@type": "SubjectMembership",
         "ownedRelatedElement": [{"@id": f"{p}-subj"}]},
        {"@id": f"{p}-subj", "@type": "ReferenceUsage", "declaredName": "housing",
         "owner": {"@id": f"{p}-req"}},
        # Grenzwert samt Einheit
        {"@id": f"{p}-fm", "@type": "FeatureMembership",
         "source": [{"@id": f"{p}-req"}],
         "ownedRelatedElement": [{"@id": f"{p}-au"}]},
        {"@id": f"{p}-au", "@type": "AttributeUsage", "declaredName": f"max{name}",
         "ownedRelationship": [{"@id": f"{p}-fv"}]},
        {"@id": f"{p}-fv", "@type": "FeatureValue",
         "ownedRelatedElement": [{"@id": f"{p}-bracket"}]},
        {"@id": f"{p}-bracket", "@type": "OperatorExpression", "operator": "[",
         "ownedRelationship": [{"@id": f"{p}-pm1"}, {"@id": f"{p}-pm2"}]},
        {"@id": f"{p}-pm1", "@type": "ParameterMembership",
         "ownedRelatedElement": [{"@id": f"{p}-f1"}]},
        {"@id": f"{p}-f1", "@type": "Feature",
         "ownedRelationship": [{"@id": f"{p}-fv1"}]},
        {"@id": f"{p}-fv1", "@type": "FeatureValue",
         "ownedRelatedElement": [{"@id": f"{p}-lit"}]},
        {"@id": f"{p}-lit", "@type": "LiteralInteger", "value": value},
        {"@id": f"{p}-pm2", "@type": "ParameterMembership",
         "ownedRelatedElement": [{"@id": f"{p}-f2"}]},
        {"@id": f"{p}-f2", "@type": "Feature",
         "ownedRelationship": [{"@id": f"{p}-fv2"}]},
        {"@id": f"{p}-fv2", "@type": "FeatureValue",
         "ownedRelatedElement": [{"@id": f"{p}-fre"}]},
        {"@id": f"{p}-fre", "@type": "FeatureReferenceExpression",
         "ownedRelationship": [{"@id": f"{p}-mem"}]},
        {"@id": f"{p}-mem", "@type": "Membership", "target": [{"@id": f"unit-{unit_short}"}]},
        {"@id": f"unit-{unit_short}", "@type": "AttributeUsage",
         "declaredShortName": unit_short, "isLibraryElement": True},
        # Constraint mit dem Vergleichsoperator
        {"@id": f"{p}-rcm", "@type": "RequirementConstraintMembership",
         "ownedRelatedElement": [{"@id": f"{p}-cu"}]},
        {"@id": f"{p}-cu", "@type": "ConstraintUsage",
         "ownedRelationship": [{"@id": f"{p}-rem"}]},
        {"@id": f"{p}-rem", "@type": "ResultExpressionMembership",
         "ownedRelatedElement": [{"@id": f"{p}-cmp"}]},
        {"@id": f"{p}-cmp", "@type": "OperatorExpression", "operator": operator},
    ]


def test_extrahiert_wert_einheit_und_operator():
    reqs = elements_to_requirements(_graph("MaxLength", 120, "mm"))
    assert len(reqs) == 1
    r = reqs[0]
    assert r.requirement_id == "MaxLength"
    assert r.operator == "<="
    assert r.limit.magnitude == 120
    assert str(r.limit.units) == "millimeter"
    assert r.subject == "housing"


def test_mehrere_anforderungen_bleiben_getrennt():
    """Kernrisiko der Traversierung: Greift der Teilbaum von MaxLength
    versehentlich auf den Grenzwert von MaxMass zu?"""
    reqs = elements_to_requirements(_graph("MaxLength", 120, "mm")
                                    + _graph("MaxMass", 0.9, "kg"))
    werte = {r.requirement_id: (r.limit.magnitude, str(r.limit.units)) for r in reqs}
    assert werte == {"MaxLength": (120, "millimeter"), "MaxMass": (0.9, "kilogram")}


def test_unvollstaendige_anforderung_wird_verworfen():
    graph = [e for e in _graph("MaxLength", 120, "mm") if e["@id"] != "maxlength-cmp"]
    assert elements_to_requirements(graph) == []


def test_bibliothekselemente_werden_ignoriert():
    graph = _graph("MaxLength", 120, "mm")
    graph[0]["isLibraryElement"] = True
    assert elements_to_requirements(graph) == []
