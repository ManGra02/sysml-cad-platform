"""Properties beliebiger CAD-Objekte lesen -- ohne einen CAD-Typ zu kennen.

Das ist der Kern der Plattform: FreeCAD liefert zu jeder Property genug
Metadaten (Typ, Gruppe, Dokumentation, Aufzaehlungswerte, Flags), um sie
generisch zu rendern. Der Editor im Browser kennt deshalb weder Part::Box noch
PartDesign::Pad.

KLASSIFIKATION NACH FAMILIE, nicht nach exaktem TypeId: es gibt 126 davon. Die
Zuordnung laeuft deshalb ueber den Python-Typ des Wertes, mit dem TypeId nur
dort, wo er noetig ist (Aufzaehlungen brauchen ihre Auswahlwerte, Links ihre
Form).

Verifizierte Fallstricke, die hier behandelt werden:
  * Label traegt das Statusflag 'Output'. Die naive Regel "Output ueberspringen"
    wuerde ausgerechnet das Umbenennen aussperren -> Allow-List.
  * Shape hat Status [] und ist ueber Flags NICHT filterbar -> Entscheidung
    haengt am TypeId.
  * Quantity.UserString ist lokalisiert ('7900,00 kg/m^3') -> nie serialisieren.
  * Rotation.Angle ist in Radiant -> Quaternion fuer die Rundreise.
  * Spreadsheet-Zellen erscheinen in PropertiesList; ein Sheet mit 20.000
    Zellen ergaebe eine ~10-MB-Antwort -> eigene Route.
"""

import FreeCAD

from cad_contract import types
from freecad_bridge.dispatch import BridgeError, main_thread_only

#: Weder lesen noch schreiben.
#: PropertyFileIncluded saugt eine beliebige Datei des Nutzers in das Dokument
#: und taugt als Pfad-Existenz-Orakel; PythonObject ist beliebiger Zustand.
DENYLIST_TYPE_IDS = frozenset(
    [
        "App::PropertyFile",
        "App::PropertyFileIncluded",
        "App::PropertyPythonObject",
    ]
)

#: Wird abgeleitet statt serialisiert.
SHAPE_TYPE_IDS = frozenset(["Part::PropertyPartShape"])

#: Schreibbar trotz Statusflags. Label ist 'Output' -- ohne diese Liste
#: koennte man nichts umbenennen.
WRITABLE_ALLOWLIST = frozenset(["Label", "Label2", "Visibility"])

#: Flags, die Schreiben verbieten (sofern nicht in der Allow-List).
BLOCKING_FLAGS = frozenset(["ReadOnly", "Output", "Transient"])

#: Interne Buchhaltung. Feuert bei jeder Geometrieaenderung mit und hat fuer
#: den Nutzer keine Bedeutung.
INTERNAL_PREFIXES = ("_",)

#: Spreadsheet-Zellen: A1, BC42 ... -- ueber eine eigene Route, nicht generisch.
_CELL_MAX_COLUMN_LETTERS = 3


def _is_cell_name(name):
    letters = 0
    for index, char in enumerate(name):
        if char.isalpha() and char.isupper():
            letters += 1
            continue
        if index == 0 or letters == 0 or letters > _CELL_MAX_COLUMN_LETTERS:
            return False
        return name[index:].isdigit()
    return False


def is_internal(name):
    return name.startswith(INTERNAL_PREFIXES)


# -- Kodierung ---------------------------------------------------------


def _ref_from_object(obj, subs=None):
    return types.obj_ref(obj.Document.Name, obj.Name, subs)


def _encode_quantity(value):
    """Einheit als Symbol, nicht als FreeCADs repr.

    str(Unit) liefert 'Unit: mm (1,0,0,0,0,0,0,0) [Length]' -- im Browser
    unbrauchbar. Das Symbol steht im Text hinter dem Zahlenwert; die
    Groessenart kommt aus Unit.Type.
    """
    text = str(value)
    parts = text.split(" ", 1)
    symbol = parts[1].strip() if len(parts) == 2 else ""

    try:
        unit_type = value.Unit.Type or None
    except Exception:
        unit_type = None

    return types.quantity(value.Value, symbol, text, unit_type)


def _encode_link_value(value):
    """Alle 24 Link-Varianten auf eine Form bringen.

    Rueckgabe ist (kind_fn, payload) oder None, wenn es kein Link ist.
    """
    if value is None:
        return types.link(None)

    if _is_document_object(value):
        return types.link(_ref_from_object(value))

    if isinstance(value, (list, tuple)):
        if not value:
            return types.link_list([])

        # (obj, ['Face1', ...]) -- ein LinkSub
        if (
            len(value) == 2
            and _is_document_object(value[0])
            and isinstance(value[1], (list, tuple, str))
        ):
            subs = value[1]
            if isinstance(subs, str):
                subs = [subs]
            return types.link_sub(_ref_from_object(value[0], subs))

        if all(_is_document_object(item) for item in value):
            return types.link_list([_ref_from_object(item) for item in value])

        # [(obj, subs), (obj2, subs2)] -- LinkSubList
        refs = []
        for item in value:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                return None
            target, subs = item
            if not _is_document_object(target):
                return None
            if isinstance(subs, str):
                subs = [subs]
            refs.append(_ref_from_object(target, subs))
        return types.link_sub_list(refs)

    return None


def _is_document_object(value):
    return hasattr(value, "Name") and hasattr(value, "Document") and hasattr(value, "TypeId")


def encode_value(obj, name, type_id):
    """Einen Property-Wert in die Vertragsform bringen.

    Liefert (status, value). status ist ENCODED, DERIVED oder UNSUPPORTED.
    """
    if type_id in DENYLIST_TYPE_IDS:
        return types.UNSUPPORTED, types.unsupported(type_id, "aus Sicherheitsgruenden gesperrt")

    if type_id in SHAPE_TYPE_IDS:
        return types.DERIVED, None  # ueber ?include=geometry

    try:
        value = getattr(obj, name)
    except Exception as exc:
        return types.UNSUPPORTED, types.unsupported(type_id, "nicht lesbar: %s" % type(exc).__name__)

    # Aufzaehlung braucht ihre Auswahlwerte -- der Wert allein genuegt nicht.
    if type_id == "App::PropertyEnumeration":
        try:
            choices = obj.getEnumerationsOfProperty(name) or []
        except Exception:
            choices = []
        return types.ENCODED, types.enum(value, choices)

    if value is None:
        # Kann ein leerer Link sein oder schlicht nichts.
        if "Link" in type_id:
            return types.ENCODED, types.link(None)
        return types.ENCODED, None

    if isinstance(value, bool):
        return types.ENCODED, value
    if isinstance(value, FreeCAD.Units.Quantity):
        return types.ENCODED, _encode_quantity(value)
    if isinstance(value, FreeCAD.Placement):
        return types.ENCODED, types.placement(list(value.Base), list(value.Rotation.Q))
    if isinstance(value, FreeCAD.Rotation):
        return types.ENCODED, types.rotation(list(value.Q))
    if isinstance(value, FreeCAD.Vector):
        return types.ENCODED, types.vector(value.x, value.y, value.z)
    if isinstance(value, FreeCAD.Matrix):
        return types.ENCODED, types.matrix(list(value.A))
    if isinstance(value, (int, float, str)):
        return types.ENCODED, value
    if isinstance(value, set):
        return types.ENCODED, types.value_set(value)
    if isinstance(value, dict):
        if all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            return types.ENCODED, types.mapping(value)
        return types.UNSUPPORTED, types.unsupported(type_id, "Abbildung mit gemischten Typen")

    material = _encode_material(value)
    if material is not None:
        return types.ENCODED, material

    if _is_document_object(value) or isinstance(value, (list, tuple)):
        encoded = _encode_link_value(value)
        if encoded is not None:
            return types.ENCODED, encoded
        encoded = _encode_simple_sequence(value, type_id)
        if encoded is not None:
            return types.ENCODED, encoded

    return types.UNSUPPORTED, types.unsupported(type_id, _summarize(value))


def _encode_material(value):
    """Materials::PropertyMaterial reist als UUID, wie FreeCAD es auch speichert."""
    uuid = getattr(value, "UUID", None)
    if uuid is None:
        return None
    return types.material_ref(uuid, getattr(value, "Name", "") or "")


def _encode_simple_sequence(value, type_id):
    """Listen aus einfachen Werten, Vektoren oder Lagen."""
    encoded = []
    for item in value:
        if isinstance(item, bool) or isinstance(item, (int, float, str)):
            encoded.append(item)
        elif isinstance(item, FreeCAD.Vector):
            encoded.append(types.vector(item.x, item.y, item.z))
        elif isinstance(item, FreeCAD.Placement):
            encoded.append(types.placement(list(item.Base), list(item.Rotation.Q)))
        elif isinstance(item, (list, tuple)) and all(
            isinstance(part, (int, float)) for part in item
        ):
            encoded.append(list(item))  # z. B. Farben
        else:
            return None
    return encoded


def _summarize(value):
    """Kurzer Hinweis statt repr().

    repr(FemMesh) waere ein kompletter Mesh-Dump, repr(Proxy) enthielte eine
    Speicheradresse, die sich bei jedem Start aendert.
    """
    name = type(value).__name__
    try:
        length = len(value)
    except TypeError:
        return name
    return "%s mit %d Eintraegen" % (name, length)


# -- Metadaten ---------------------------------------------------------


def _flags(obj, name):
    try:
        return list(obj.getTypeOfProperty(name))
    except Exception:
        return []


def _is_dynamic(obj, name):
    """Dynamische Properties tragen Statuscode 21.

    getPropertyStatus() liefert fuer eine konkrete Property rohe Ints; die
    NAMEN kommen aus getTypeOfProperty(). Fuer 'dynamisch' gibt es keinen
    Namen, deshalb hier ausnahmsweise der Code.
    """
    try:
        return 21 in obj.getPropertyStatus(name)
    except Exception:
        return False


def _expression_for(obj, name):
    try:
        engine = obj.ExpressionEngine
    except Exception:
        return None
    for path, expression in engine or []:
        if path == name:
            return expression
    return None


def _is_writable(name, type_id, status, flags, expression):
    if status != types.ENCODED:
        return False
    if type_id in DENYLIST_TYPE_IDS or type_id in SHAPE_TYPE_IDS:
        return False
    if expression:
        return False  # wuerde beim naechsten Recompute ueberschrieben
    if name in WRITABLE_ALLOWLIST:
        return True
    return not any(flag in BLOCKING_FLAGS for flag in flags)


@main_thread_only
def describe_property(obj, name):
    """Eine Property vollstaendig beschreiben."""
    try:
        type_id = obj.getTypeIdOfProperty(name)
    except Exception:
        type_id = "unbekannt"

    status, value = encode_value(obj, name, type_id)
    flags = _flags(obj, name)
    expression = _expression_for(obj, name)

    try:
        group = obj.getGroupOfProperty(name)
    except Exception:
        group = None
    try:
        documentation = obj.getDocumentationOfProperty(name)
    except Exception:
        documentation = None

    return types.property_entry(
        name=name,
        type_id=type_id,
        status=status,
        value=value,
        group=group,
        doc=documentation,
        flags=flags,
        writable=_is_writable(name, type_id, status, flags, expression),
        dynamic=_is_dynamic(obj, name),
        expression=expression,
    )


@main_thread_only
def property_names(obj, include_internal=False):
    """Relevante Property-Namen eines Objekts.

    Spreadsheet-Zellen werden ausgeschlossen: sie erscheinen in PropertiesList,
    gehoeren aber ueber eine eigene Bereichsroute.
    """
    try:
        names = list(obj.PropertiesList)
    except Exception:
        return []

    is_sheet = getattr(obj, "TypeId", "").startswith("Spreadsheet::")
    result = []
    for name in names:
        if not include_internal and is_internal(name):
            continue
        if is_sheet and _is_cell_name(name):
            continue
        result.append(name)
    return sorted(result)


@main_thread_only
def describe_properties(obj, fields=None, include_internal=False):
    """Alle (oder ausgewaehlte) Properties beschreiben.

    ``fields`` begrenzt auf eine explizite Liste -- das ist der Weg fuer die
    Batch-Route, damit eine Tabelle mit drei Spalten nicht das ganze Objekt
    ueberträgt.
    """
    names = property_names(obj, include_internal=include_internal)
    if fields is not None:
        wanted = set(fields)
        names = [name for name in names if name in wanted]
    return [describe_property(obj, name) for name in names]


# -- Rueckwandlung (M3) ------------------------------------------------


class InvalidValue(BridgeError):
    """Der Wert passt nicht zur Property -- nichts wurde geschrieben."""

    code = "invalid_value"
    http_status = 400


class NotWritable(BridgeError):
    code = "not_writable"
    http_status = 409


class ExpressionBound(BridgeError):
    """Ein literaler Wert wuerde beim naechsten Recompute still verworfen."""

    code = "expression_bound"
    http_status = 409


def _payload_form(payload, kind):
    """Die Vertragsform ({"kind": ...}) erkennen, sonst None."""
    if isinstance(payload, dict) and payload.get("kind") == kind:
        return payload
    return None


def _resolve_ref(doc, ref, name):
    if ref is None:
        return None
    if not isinstance(ref, dict) or "name" not in ref:
        raise InvalidValue("%s: Referenz braucht {doc, name}" % name, name)
    target_doc = doc
    if ref.get("doc") and ref["doc"] != doc.Name:
        try:
            target_doc = FreeCAD.getDocument(ref["doc"])
        except Exception:
            target_doc = None
        if target_doc is None:
            # Kein Nachladen: das waere ein mehrsekuendiger Block im Dispatch.
            raise InvalidValue(
                "%s: Zieldokument %r ist nicht offen" % (name, ref["doc"]), name
            )
    target = target_doc.getObject(ref["name"])
    if target is None:
        raise InvalidValue(
            "%s: Objekt %r nicht gefunden (Referenz ueber Name, nicht Label)"
            % (name, ref["name"]),
            name,
        )
    return target


def _decode_quantity(name, current, payload):
    form = _payload_form(payload, types.QUANTITY)
    if form is not None:
        payload = form.get("text") or form.get("value")
    if isinstance(payload, bool):
        raise InvalidValue("%s: Menge erwartet" % name, name)
    if isinstance(payload, (int, float)):
        return float(payload)  # in FreeCADs internen Einheiten
    if not isinstance(payload, str):
        raise InvalidValue("%s: Menge erwartet" % name, name)
    try:
        quantity = FreeCAD.Units.Quantity(payload)
    except Exception:
        raise InvalidValue("%s: %r ist keine gueltige Menge" % (name, payload), name)
    # Eine reine Zahl als Text ("25") ist dimensionslos und wird als interne
    # Einheit verstanden. Alles andere muss zur Groessenart passen -- FreeCAD
    # wuerde "3 kg" auf eine Laenge sonst mit ArithmeticError quittieren.
    dimensionless = tuple(quantity.Unit.Signature) == (0,) * 8
    if not dimensionless and tuple(quantity.Unit.Signature) != tuple(current.Unit.Signature):
        raise InvalidValue(
            "%s: Einheit passt nicht, erwartet %s"
            % (name, current.Unit.Type or "dimensionslos"),
            name,
        )
    return quantity.Value if dimensionless else quantity


def _decode_links(doc, name, payload):
    kind = payload.get("kind")
    if kind == types.LINK:
        return _resolve_ref(doc, payload.get("ref"), name)
    if kind == types.LINK_LIST:
        return [_resolve_ref(doc, ref, name) for ref in payload.get("refs", [])]
    if kind == types.LINK_SUB:
        ref = payload.get("ref")
        target = _resolve_ref(doc, ref, name)
        return (target, list(ref.get("subs", []))) if target is not None else None
    if kind == types.LINK_SUB_LIST:
        return [
            (_resolve_ref(doc, ref, name), list(ref.get("subs", [])))
            for ref in payload.get("refs", [])
        ]
    return _NO_MATCH


_NO_MATCH = object()


def _decode_value(obj, name, type_id, current, payload):
    """Anhand des AKTUELLEN Werts entscheiden, welche Form erwartet wird."""
    if type_id == "App::PropertyEnumeration":
        value = payload.get("value") if isinstance(payload, dict) else payload
        # Eine LISTE wuerde die Auswahlwerte ersetzen, statt einen zu waehlen.
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise InvalidValue("%s: Aufzaehlung erwartet str oder int" % name, name)
        choices = obj.getEnumerationsOfProperty(name) or []
        if isinstance(value, str) and value not in choices:
            raise InvalidValue(
                "%s: %r ist keine erlaubte Auswahl" % (name, value), {"choices": choices}
            )
        if isinstance(value, int) and not 0 <= value < len(choices):
            raise InvalidValue("%s: Index %d ausserhalb der Auswahl" % (name, value), name)
        return value

    if isinstance(current, bool):
        if not isinstance(payload, bool):
            raise InvalidValue("%s: bool erwartet" % name, name)
        return payload

    if isinstance(current, FreeCAD.Units.Quantity):
        return _decode_quantity(name, current, payload)

    if isinstance(current, FreeCAD.Placement):
        form = _payload_form(payload, types.PLACEMENT)
        if form is None or len(form.get("pos") or []) != 3 or len(form.get("q") or []) != 4:
            raise InvalidValue("%s: {kind: placement, pos[3], q[4]} erwartet" % name, name)
        return FreeCAD.Placement(FreeCAD.Vector(*form["pos"]), FreeCAD.Rotation(*form["q"]))

    if isinstance(current, FreeCAD.Rotation):
        form = _payload_form(payload, types.ROTATION)
        if form is None or len(form.get("q") or []) != 4:
            raise InvalidValue("%s: {kind: rotation, q[4]} erwartet" % name, name)
        return FreeCAD.Rotation(*form["q"])

    if isinstance(current, FreeCAD.Vector):
        form = _payload_form(payload, types.VECTOR)
        if form is None:
            raise InvalidValue("%s: {kind: vector, x, y, z} erwartet" % name, name)
        return FreeCAD.Vector(form["x"], form["y"], form["z"])

    if isinstance(current, int):
        if isinstance(payload, bool) or not isinstance(payload, int):
            raise InvalidValue("%s: Ganzzahl erwartet" % name, name)
        return payload

    if isinstance(current, float):
        if isinstance(payload, bool) or not isinstance(payload, (int, float)):
            raise InvalidValue("%s: Zahl erwartet" % name, name)
        return float(payload)

    if isinstance(current, str):
        if not isinstance(payload, str):
            raise InvalidValue("%s: Text erwartet" % name, name)
        return payload

    if isinstance(payload, dict):
        decoded = _decode_links(obj.Document, name, payload)
        if decoded is not _NO_MATCH:
            return decoded
        kind = payload.get("kind")
        if kind == types.MAP:
            entries = payload.get("entries") or {}
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in entries.items()):
                raise InvalidValue("%s: Abbildung str -> str erwartet" % name, name)
            return dict(entries)
        if kind == types.MATERIAL_REF:
            try:
                import Materials

                return Materials.MaterialManager().getMaterial(payload.get("uuid"))
            except Exception:
                raise InvalidValue(
                    "%s: Material %r unbekannt" % (name, payload.get("uuid")), name
                )

    raise InvalidValue("%s: Wertform fuer %s nicht unterstuetzt" % (name, type_id), name)


@main_thread_only
def decode_for_write(obj, name, payload):
    """Pruefen, ob ``name`` schreibbar ist, und den FreeCAD-Wert bauen.

    Wird fuer ALLE Felder aufgerufen, BEVOR die Transaktion geoeffnet wird: ein
    ungueltiges Feld soll nichts anfassen, statt eine halbe Aenderung
    zurueckrollen zu muessen.
    """
    if name not in obj.PropertiesList or is_internal(name):
        raise InvalidValue("%s: unbekannte Property" % name, name)

    entry = describe_property(obj, name)
    if entry["expression"]:
        raise ExpressionBound(
            "%s ist an die Expression %r gebunden" % (name, entry["expression"]), name
        )
    if not entry["writable"]:
        raise NotWritable("%s ist nicht schreibbar (%s)" % (name, entry["typeId"]), name)

    return _decode_value(obj, name, entry["typeId"], getattr(obj, name), payload)
