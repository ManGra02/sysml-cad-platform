"""Reference part of the PoC.

Convention (phase 0): every later-measurable quantity hangs off a named module
parameter, never off a face or edge index. That is what sidesteps the
topological naming problem -- indices move when the model is rebuilt, names do
not.

The parameter names are the interface the mapping addresses, so the suffixes
matter: `_MM`, `_KG` and `_G_PER_CM3` are how the adapter attaches units (see
adapters/build123d_adapter.py).
"""

from build123d import BuildPart, Box, Hole, Part

# --- named parameters: this is the interface to the mapping ------------------
LENGTH_MM = 118.0
WIDTH_MM = 60.0
HEIGHT_MM = 40.0
BORE_RADIUS_MM = 8.0

# --- material: read by the adapter, no longer duplicated in mapping.yaml -----
MATERIAL = "AlSi10Mg"
DENSITY_G_PER_CM3 = 2.70

# Axis along which "length" is measured. Explicit, not implied.
LENGTH_AXIS = "X"


def build() -> Part:
    with BuildPart() as housing:
        Box(LENGTH_MM, WIDTH_MM, HEIGHT_MM)
        Hole(radius=BORE_RADIUS_MM)
    return housing.part


if __name__ == "__main__":
    from build123d import export_step

    part = build()
    bb = part.bounding_box()
    print(f"Volume       : {part.volume:10.2f} mm^3")
    print(f"Bounding box : {bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f} mm")
    print(f"Faces        : {len(part.faces())}")
    export_step(part, "out/motor_housing.step")
    print("STEP written: out/motor_housing.step")
