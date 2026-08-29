"""Show what is inside a STEP file.

The counterpart to explore.py, which does the same for the SysML side. Without
this you cannot write a mapping for a file you did not author: the node names
are the addresses, and there is no other way to learn them.

    python -m sysmlcad.explore_cad fixtures/step/gearbox.step

It prints the reference string for each node in the form mapping.yaml expects,
so writing the mapping is copy-and-paste rather than guesswork.
"""

from __future__ import annotations

import sys

from .adapters import Unsupported
from .adapters.step_adapter import StepAdapter


def describe(path: str) -> int:
    adapter = StepAdapter()

    try:
        nodes = adapter.tree(path)
    except Unsupported as exc:
        print(f"error: {exc}")
        return 1

    print(f"\n{path}")
    print(f"state    : step:{adapter.state_id()}")
    print(f"nodes    : {len(nodes)}\n")

    header = f"{'node':<34} {'kind':<9} {'volume [mm3]':>15} {'bbox X/Y/Z [mm]':>26}"
    print(header)
    print("-" * len(header))

    duplicates: dict[str, int] = {}
    for _, node in nodes:
        duplicates[node.name] = duplicates.get(node.name, 0) + 1

    for depth, node in nodes:
        ref = f"{path}#{node.name}" if depth else path
        try:
            shape = adapter.shape_of(ref)
            volume = f"{shape.volume:15.2f}"
            size = shape.bounding_box().size
            bbox = f"{size.X:7.2f} /{size.Y:7.2f} /{size.Z:7.2f}"
        except Unsupported as exc:
            volume, bbox = "  --", f"({exc})"

        label = "   " * depth + node.name
        kind = "assembly" if node.is_assembly else "part"
        print(f"{label:<34} {kind:<9} {volume:>15} {bbox:>26}")

    print("\nreference strings for mapping.yaml:")
    for depth, node in nodes:
        if node.is_assembly and depth == 0 and len(nodes) > 1:
            continue
        marker = "  # AMBIGUOUS, cannot be addressed by name" if duplicates[node.name] > 1 else ""
        ref = path if not depth else f"{path}#{node.name}"
        print(f"    cad_object: {ref}{marker}")

    material_notes = []
    for depth, node in nodes:
        ref = f"{path}#{node.name}" if depth else path
        try:
            material = adapter.material(ref)
        except Unsupported:
            material = None
        if material is None:
            material_notes.append(node.name)

    if material_notes:
        print(
            f"\nno material in the file for: {', '.join(material_notes)}\n"
            f"  -> `mass` needs `args: {{density_g_per_cm3: ...}}` in the mapping,\n"
            f"     otherwise the run reports a gap instead of inventing a density."
        )
    print()
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m sysmlcad.explore_cad <file.step>")
        return 2
    return describe(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
