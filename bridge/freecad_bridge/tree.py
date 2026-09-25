"""Der Objektbaum -- so, wie der Nutzer ihn in FreeCAD daneben sieht.

Das sind technisch ZWEI verschiedene Graphen, und die Wahl ist bewusst:

  claimChildren()   reproduziert FreeCADs Baum exakt: ein Body beansprucht
                    seine Features, ein Cut seine Base und Tool, ein Origin
                    seine Ebenen. GUI-gebunden -- headless ist ViewObject None.
  Group/OriginFeatures  deterministisch und headless testbar, VERLIERT aber
                    Objekte (in AssemblyExample 8 von 56: Origin samt Datum-
                    Achsen und -Ebenen).
  OutList           ERFINDET Objekte: 5 Objekte werden zu 8 Knoten, ein
                    geteilter Body erscheint unter 50 Links 50-fach, Zyklen
                    sind moeglich.

Deshalb: claimChildren primaer, pro Knoten mit Fallback, am Ende Abgleich
gegen doc.Objects. Fuer ein Synchronisationsprojekt waere "sieht anders aus als
FreeCAD" ein dauerhaftes Glaubwuerdigkeitsproblem.

Uebertragen wird eine FLACHE LISTE plus explizite Kanten. Die Struktur ist ein
DAG, kein Baum: ein Objekt darf mehrfach vorkommen. Der React-Key ist deshalb
der Pfad, nicht obj.Name.
"""

from freecad_bridge import objects as objects_mod
from freecad_bridge.dispatch import main_thread_only
from freecad_bridge.documents import get_document

CLAIM = "claimChildren"
FALLBACK = "group"


def _claim_children(obj):
    """Kinder laut FreeCADs eigener Baumlogik -- oder None.

    claimChildren ist bei Arch, Draft und Assembly in Python implementiert und
    kann werfen. Ein Fehler hier darf nicht den ganzen Baum kosten.
    """
    view_object = getattr(obj, "ViewObject", None)
    if view_object is None:
        return None
    claim = getattr(view_object, "claimChildren", None)
    if claim is None:
        return None
    try:
        children = claim()
    except Exception:
        return None
    if children is None:
        return None
    return [child for child in children if child is not None]


def _fallback_children(obj):
    """Ohne GUI: Group plus die Origin-Infrastruktur."""
    children = []
    for attribute in ("Group", "OriginFeatures"):
        value = getattr(obj, attribute, None)
        if not value:
            continue
        try:
            children.extend(item for item in value if item is not None)
        except TypeError:
            continue

    origin = getattr(obj, "Origin", None)
    if origin is not None:
        children.append(origin)
    return children


@main_thread_only
def build_tree(doc_name, include_internal=False):
    """Flache Knotenliste plus Kanten."""
    doc = get_document(doc_name)
    all_objects = list(doc.Objects)

    nodes = {}
    children_of = {}
    deps_of = {}
    source_of = {}
    claimed = set()

    for obj in all_objects:
        nodes[obj.Name] = objects_mod.summarize_object(obj)

        children = _claim_children(obj)
        if children is None:
            children = _fallback_children(obj)
            source_of[obj.Name] = FALLBACK
        else:
            source_of[obj.Name] = CLAIM

        # Selbstbezug kommt vor und wuerde den Aufbau im Frontend aufhaengen.
        child_names = [
            child.Name
            for child in children
            if getattr(child, "Name", None) and child.Name != obj.Name
        ]
        children_of[obj.Name] = child_names
        claimed.update(child_names)

        deps_of[obj.Name] = [
            dep.Name
            for dep in (getattr(obj, "OutList", []) or [])
            if getattr(dep, "Name", None) and dep.Name != obj.Name
        ]

    # Wurzeln: alles, was niemand als Kind beansprucht. Das ist der Abgleich
    # gegen doc.Objects -- so geht kein Objekt verloren, auch wenn eine
    # claimChildren-Implementierung etwas verschweigt.
    roots = [name for name in nodes if name not in claimed]

    if not include_internal:
        visible = {name for name, node in nodes.items() if not node["internal"]}
        nodes = {name: node for name, node in nodes.items() if name in visible}
        children_of = {
            name: [child for child in kids if child in visible]
            for name, kids in children_of.items()
            if name in visible
        }
        deps_of = {
            name: [dep for dep in deps if dep in visible]
            for name, deps in deps_of.items()
            if name in visible
        }
        roots = [name for name in roots if name in visible]

    for name, node in nodes.items():
        node["children"] = children_of.get(name, [])
        node["deps"] = deps_of.get(name, [])
        node["childSource"] = source_of.get(name)

    return {
        "doc": doc_name,
        "roots": sorted(roots),
        "nodes": nodes,
        "objectCount": len(all_objects),
        "hiddenInternal": len(all_objects) - len(nodes),
        # Sagt der Oberflaeche, ob der Baum FreeCADs Ansicht entspricht oder
        # aus dem Fallback stammt (dann fehlen z. B. Origin-Kinder).
        "guiAccurate": all(source == CLAIM for source in source_of.values()) if source_of else False,
    }
