"""Generate the STEP fixtures the tests run against.

Committed rather than generated at test time: the STEP adapter has to read
files this project did not author, so its tests must not depend on build123d
being able to write them. Generating them here keeps them reproducible and
reviewable; `make step-fixtures` regenerates them.

What they prove and what they do not: these files exercise the mechanism --
names, assembly tree, unit conversion, measurement. They say nothing about the
quirks of any particular exporter. Validating against a real FreeCAD export is
a separate step, and the one that actually matters.
"""

from pathlib import Path

from build123d import Unit, export_step

import gearbox
import motor_housing

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "step"

FIXTURES = [
    # (filename, shape, unit, why it exists)
    ("motor_housing.step", motor_housing.build(), Unit.MM,
     "single part, mirrors the build123d reference"),
    ("gearbox.step", gearbox.build(), Unit.MM,
     "assembly with two named nodes"),
    # build123d works in millimetres, and export_step(unit=...) only DECLARES
    # the unit -- it does not rescale. So to get a file that genuinely holds an
    # inch-authored part, the geometry is scaled down first. Read back, it must
    # land on the original millimetre dimensions again.
    ("motor_housing_inch.step", motor_housing.build().scale(1 / 25.4), Unit.IN,
     "authored in inches -- must still read back as millimetres"),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, shape, unit, why in FIXTURES:
        path = OUT / name
        export_step(shape, str(path), unit=unit)
        size = path.stat().st_size
        print(f"{name:<28} {size / 1024:6.1f} KB  {unit.name:<3}  {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
