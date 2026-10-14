"""Show what is inside a STEP file or a FreeCAD document.

The counterpart to explore.py, which does the same for the SysML side. Without
this you cannot write a mapping for a file you did not author: the node names
are the addresses, and there is no other way to learn them.

    python -m sysmlcad.explore_cad fixtures/step/gearbox.step
    python -m sysmlcad.explore_cad projects/cube_freecad/cube.FCStd   (needs the worker)

It prints the reference string for each node in the form mapping.yaml expects,
so writing the mapping is copy-and-paste rather than guesswork.

The node list, the reference strings and the material notes all come from
`adapter.catalog()` -- the same data a mapping proposal is built from, so what
you read here is exactly what the proposer sees. This module only adds the
measurements, which a catalogue deliberately does not carry.
"""

from __future__ import annotations

import sys

from .adapters import Unsupported
from .adapters.freecad_adapter import FreeCadAdapter
from .adapters.step_adapter import StepAdapter


def describe_freecad(path: str) -> int:
    """A FreeCAD document: objects, the measurements each offers, and the named
    parameters -- the thing a STEP export cannot show."""
    adapter = FreeCadAdapter()
    targets = adapter.catalog([path])
    if len(targets) == 1 and not targets[0].addressable and targets[0].note.startswith("not readable"):
        print(f"error: {targets[0].note}")
        return 1

    print(f"\n{path}")
    print(f"state    : freecad:{adapter.state_id()}")
    print(f"objects  : {len(targets)}\n")
    header = f"{'object':<34} {'kind':<9} {'bbox X/Y/Z [mm]':>26}  note"
    print(header)
    print("-" * len(header))
    for target in targets:
        try:
            size = [adapter.measure(target.reference, "bbox_size", {"axis": a}).magnitude
                    for a in "XYZ"]
            bbox = f"{size[0]:7.2f} /{size[1]:7.2f} /{size[2]:7.2f}"
        except Unsupported as exc:
            bbox = f"({exc})"
        print(f"{'   ' * target.depth + target.name:<34} {target.kind:<9} {bbox:>26}  {target.note}")

    parameters = targets[0].parameters if targets else {}
    if parameters:
        print("\nnamed parameters (method: parameter, args: {name: ...}):")
        for name, value in sorted(parameters.items()):
            print(f"    {name:<40} {value:.4g~P}")

    print("\nreference strings for mapping.yaml:")
    for target in targets:
        marker = "" if target.addressable else f"  # {target.note}"
        print(f"    cad_object: {target.reference}{marker}")
    print()
    return 0


def describe(path: str) -> int:
    if path.lower().endswith(".fcstd"):
        return describe_freecad(path)
    adapter = StepAdapter()

    try:
        targets = adapter.catalog([path])
    except Unsupported as exc:
        print(f"error: {exc}")
        return 1
    if not targets:
        print(f"error: nothing readable in {path}")
        return 1

    print(f"\n{path}")
    print(f"state    : step:{adapter.state_id()}")
    print(f"nodes    : {len(targets)}\n")

    header = f"{'node':<34} {'kind':<9} {'volume [mm3]':>15} {'bbox X/Y/Z [mm]':>26}"
    print(header)
    print("-" * len(header))

    for target in targets:
        try:
            shape = adapter.shape_of(target.reference)
            volume = f"{shape.volume:15.2f}"
            size = shape.bounding_box().size
            bbox = f"{size.X:7.2f} /{size.Y:7.2f} /{size.Z:7.2f}"
        except Unsupported as exc:
            volume, bbox = "  --", f"({exc})"

        print(f"{'   ' * target.depth + target.name:<34} {target.kind:<9} "
              f"{volume:>15} {bbox:>26}")

    print("\nreference strings for mapping.yaml:")
    for target in targets:
        if target.kind == "assembly" and target.depth == 0 and len(targets) > 1:
            continue
        marker = "" if target.addressable else f"  # {target.note}"
        print(f"    cad_object: {target.reference}{marker}")

    without_material = [t.name for t in targets if "no material" in t.note]
    if without_material:
        print(
            f"\nno material in the file for: {', '.join(without_material)}\n"
            f"  -> `mass` from this file is a gap, not an invented density. Measure\n"
            f"     it where the material is declared (a build123d script), or pass\n"
            f"     `args: {{density_g_per_cm3: ...}}` for a what-if study -- a density\n"
            f"     committed to mapping.yaml fails the test suite on purpose."
        )
    print()
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m sysmlcad.explore_cad <file.step | file.FCStd>")
        return 2
    return describe(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
