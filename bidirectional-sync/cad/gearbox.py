"""Two-part reference assembly.

Exists so that assembly handling is exercised by something: a single part
cannot show a mass budget summed over components, nor an interface dimension
agreed between two of them.

The bore is the interface: housing and cover must agree on it. That is the
"interface control" case from the use-case slides -- one designer widening the
bore on one side without telling the other is exactly what a check like this is
supposed to surface.

Same convention as motor_housing.py: every measurable quantity hangs off a
named module parameter, never a face or edge index.
"""

from build123d import Box, BuildPart, Compound, Cylinder, Location, Mode, Part

# --- named parameters: the interface to the mapping --------------------------
HOUSING_LENGTH_MM = 90.0
HOUSING_WIDTH_MM = 60.0
HOUSING_HEIGHT_MM = 40.0

COVER_THICKNESS_MM = 6.0

# The agreed interface dimension. Both parts read it; neither owns it alone.
BORE_RADIUS_MM = 8.0

MATERIAL = "AlSi10Mg"
DENSITY_G_PER_CM3 = 2.70

# Node names as they appear in the exported STEP file, and therefore as they
# must be written in mapping.yaml after the '#'.
HOUSING_NAME = "Housing"
COVER_NAME = "Cover"
ASSEMBLY_NAME = "Gearbox"


def build_housing() -> Part:
    with BuildPart() as housing:
        Box(HOUSING_LENGTH_MM, HOUSING_WIDTH_MM, HOUSING_HEIGHT_MM)
        Cylinder(radius=BORE_RADIUS_MM, height=HOUSING_HEIGHT_MM, mode=Mode.SUBTRACT)
    return housing.part


def build_cover() -> Part:
    with BuildPart() as cover:
        Box(HOUSING_LENGTH_MM, HOUSING_WIDTH_MM, COVER_THICKNESS_MM)
        Cylinder(radius=BORE_RADIUS_MM, height=COVER_THICKNESS_MM, mode=Mode.SUBTRACT)
    return cover.part


def build() -> Compound:
    """The assembly, with labelled children -- the labels become STEP names."""
    housing = build_housing()
    housing.label = HOUSING_NAME

    cover = build_cover()
    cover.label = COVER_NAME
    cover.locate(Location((0, 0, (HOUSING_HEIGHT_MM + COVER_THICKNESS_MM) / 2)))

    assembly = Compound(children=[housing, cover])
    assembly.label = ASSEMBLY_NAME
    return assembly


if __name__ == "__main__":
    asm = build()
    bb = asm.bounding_box()
    print(f"Assembly     : {asm.label}")
    for child in asm.children:
        print(f"  {child.label:<10} volume {child.volume:10.2f} mm^3")
    print(f"Total volume : {asm.volume:10.2f} mm^3")
    print(f"Bounding box : {bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f} mm")
