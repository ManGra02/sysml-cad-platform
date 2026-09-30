"""The object tree -- as the user sees it in FreeCAD next to it.

Technically these are TWO different graphs, and the choice is deliberate:

  claimChildren()   reproduces FreeCAD's tree exactly: a Body claims its
                    features, a Cut its Base and Tool, an Origin its
                    planes. GUI-bound -- headless, ViewObject is None.
  Group/OriginFeatures  deterministic and testable headless, but LOSES
                    objects (in AssemblyExample 8 of 56: Origin along with
                    datum axes and planes).
  OutList           INVENTS objects: 5 objects become 8 nodes, a shared
                    Body appears 50 times under 50 links, cycles are
                    possible.

Hence: claimChildren first, with a fallback per node, and at the end a
reconciliation against doc.Objects. For a synchronization project, "looks
different from FreeCAD" would be a permanent credibility problem.

What is transferred is a FLAT LIST plus explicit edges. The structure is a
DAG, not a tree: an object may occur more than once. The React key is
therefore the path, not obj.Name.
"""

from freecad_bridge import objects as objects_mod
from freecad_bridge.dispatch import main_thread_only
from freecad_bridge.documents import get_document

CLAIM = "claimChildren"
FALLBACK = "group"


def _claim_children(obj):
    """Children according to FreeCAD's own tree logic -- or None.

    claimChildren is implemented in Python for Arch, Draft and Assembly and
    can raise. An error here must not cost the whole tree.
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
    """Without a GUI: Group plus the Origin infrastructure."""
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
    """Flat node list plus edges."""
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

        # Self-references occur and would hang the build-up in the frontend.
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

    # Roots: everything nobody claims as a child. This is the reconciliation
    # against doc.Objects -- so no object gets lost, even if a
    # claimChildren implementation leaves something out.
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
        # Tells the UI whether the tree matches FreeCAD's view or comes
        # from the fallback (in which case e.g. Origin children are missing).
        "guiAccurate": all(source == CLAIM for source in source_of.values()) if source_of else False,
    }
