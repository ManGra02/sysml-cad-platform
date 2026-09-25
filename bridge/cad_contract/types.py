"""Das Wertformat auf der Leitung.

Abhaengigkeitsfrei und in FreeCADs 3.11 wie in der Backend-venv importierbar.
Hier steht, WIE etwas aussieht -- nicht, wie es aus FreeCAD geholt wird. Die
Umwandlung liegt in freecad_bridge.properties.

DREI AUSGAENGE fuer jede Property, nie mehr:

  encoded      Ein definiertes Format, das der Editor rendern und
               zurueckschreiben kann.
  derived      Abgeleitet, nur lesbar (Shape -> Volume/BoundBox/ShapeType).
  unsupported  Vorhanden, aber hier nicht editierbar. Die Oberflaeche zeigt
               das ehrlich an.

Es gibt bewusst KEINEN str()-Fallback. repr() eines FEM-Meshes ist ein
kompletter Mesh-Dump, und repr() eines Proxy-Objekts enthaelt eine
Speicheradresse, die sich bei jedem Start aendert -- der Cache saehe dann
dauernd Aenderungen, die keine sind.
"""

# -- Kind-Marker fuer kodierte Werte -----------------------------------

QUANTITY = "quantity"
VECTOR = "vector"
PLACEMENT = "placement"
ROTATION = "rotation"
MATRIX = "matrix"
COLOR = "color"
ENUM = "enum"
LINK = "link"
LINK_LIST = "link_list"
LINK_SUB = "link_sub"
LINK_SUB_LIST = "link_sub_list"
MATERIAL_REF = "material_ref"
MAP = "map"
SET = "set"
UNSUPPORTED = "unsupported"

#: Status einer Property im Transport.
ENCODED = "encoded"
DERIVED = "derived"


def obj_ref(doc, name, subs=None):
    """Der EINZIGE Schluessel fuer ein Objekt ueber die Prozessgrenze.

    Immer (doc.Name, obj.Name) -- beide unveraenderlich und pro Dokument
    eindeutig. NIE obj.Label: das ist ein reines Anzeigefeld und nicht
    eindeutig. In AssemblyExample.FCStd traegt das Objekt mit Name 'Shape001'
    das Label 'Base', waehrend ein ANDERES Objekt 'Base' heisst -- ein
    Label-als-Name-Request patcht lautlos das falsche Objekt, ohne 404.
    """
    ref = {"doc": doc, "name": name}
    if subs:
        ref["subs"] = list(subs)
    return ref


# -- Wertformen --------------------------------------------------------


def quantity(value, unit, text, unit_type=None):
    """Menge mit Einheit.

    ``value``     immer in FreeCADs INTERNEN Einheiten (mm, kg, s, Grad)
    ``unit``      das Symbol zum Anzeigen ('mm', 'kg/mm^3'), leer bei dimensionslos
    ``unit_type`` die Groessenart ('Length', 'Density') -- damit die Oberflaeche
                  ein passendes Eingabefeld waehlen kann
    ``text``      die verlustfreie Rundreise-Form, str(Quantity)

    NIE UserString verwenden: der ist lokalisiert ('7900,00 kg/m^3') und damit
    weder vergleichbar noch zurueck parsebar.
    """
    return {
        "kind": QUANTITY,
        "value": value,
        "unit": unit,
        "unitType": unit_type,
        "text": text,
    }


def vector(x, y, z):
    return {"kind": VECTOR, "x": x, "y": y, "z": z}


def placement(position, quaternion):
    """Lage als Position + Quaternion.

    Quaternion, nicht Yaw-Pitch-Roll: Rotation.Angle ist in Radiant, und nur
    ueber .Q ist die Rundreise verlustfrei.
    """
    return {"kind": PLACEMENT, "pos": list(position), "q": list(quaternion)}


def rotation(quaternion):
    return {"kind": ROTATION, "q": list(quaternion)}


def matrix(values):
    return {"kind": MATRIX, "a": list(values)}


def color(rgba):
    return {"kind": COLOR, "rgba": list(rgba)}


def enum(value, choices):
    """Aufzaehlung.

    Beim Schreiben nur str oder int senden: eine LISTE ersetzt die Auswahlwerte,
    statt einen auszuwaehlen.
    """
    return {"kind": ENUM, "value": value, "choices": list(choices or [])}


def link(ref):
    return {"kind": LINK, "ref": ref}


def link_list(refs):
    return {"kind": LINK_LIST, "refs": list(refs)}


def link_sub(ref):
    return {"kind": LINK_SUB, "ref": ref}


def link_sub_list(refs):
    return {"kind": LINK_SUB_LIST, "refs": list(refs)}


def material_ref(uuid, name):
    """Material reist als UUID.

    FreeCAD persistiert ShapeMaterial ebenfalls nur als UUID -- selbst erzeugte
    Materialien ueberleben Speichern/Laden nicht.
    """
    return {"kind": MATERIAL_REF, "uuid": uuid, "name": name}


def mapping(pairs):
    return {"kind": MAP, "entries": dict(pairs)}


def value_set(values):
    return {"kind": SET, "values": sorted(values)}


def unsupported(type_id, summary):
    """Vorhanden, aber nicht transportierbar. Ehrlich statt str()."""
    return {"kind": UNSUPPORTED, "typeId": type_id, "summary": summary}


# -- Property-Beschreibung ---------------------------------------------


def property_entry(name, type_id, status, value, group=None, doc=None,
                   flags=(), writable=False, dynamic=False, expression=None):
    """Eine Property samt allem, was der generische Editor zum Rendern braucht."""
    return {
        "name": name,
        "typeId": type_id,
        "status": status,          # ENCODED | DERIVED | UNSUPPORTED
        "value": value,
        "group": group,
        "doc": doc,
        "flags": list(flags),
        "writable": bool(writable),
        "dynamic": bool(dynamic),
        "expression": expression,  # gebunden -> Schreiben waere wirkungslos
    }
