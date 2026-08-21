"""Referenzbauteil des PoC.

Konvention (Phase 0): jede spaeter messbare Groesse haengt an einem
benannten Modulparameter, niemals an einem Flaechen- oder Kantenindex.
Genau das umgeht das topologische Namensproblem.
"""

from build123d import BuildPart, Box, Hole, Part

# --- benannte Parameter: das ist die Schnittstelle zum Mapping ---------------
LENGTH_MM = 118.0
WIDTH_MM = 60.0
HEIGHT_MM = 40.0
BORE_RADIUS_MM = 8.0

DENSITY_G_PER_CM3 = 2.70  # AlSi10Mg

# Achse, entlang derer "Laenge" gemessen wird. Explizit, nicht implizit.
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
    print(f"Volumen      : {part.volume:10.2f} mm^3")
    print(f"Bounding-Box : {bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f} mm")
    print(f"Flaechen     : {len(part.faces())}")
    export_step(part, "out/motor_housing.step")
    print("STEP geschrieben: out/motor_housing.step")
