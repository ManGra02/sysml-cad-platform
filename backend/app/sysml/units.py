"""Unit normalisation to SI. Keep this in the common model so SysML and CAD compare like with like
(FreeCAD reports mm / kg by default, SysML v2 models use ISQ/SI library units)."""
from __future__ import annotations

# symbol -> (factor to SI, SI symbol)
_UNITS: dict[str, tuple[float, str]] = {
    # mass
    "kg": (1.0, "kg"), "g": (1e-3, "kg"), "mg": (1e-6, "kg"), "t": (1e3, "kg"),
    # length
    "m": (1.0, "m"), "mm": (1e-3, "m"), "cm": (1e-2, "m"), "dm": (1e-1, "m"), "km": (1e3, "m"), "um": (1e-6, "m"), "μm": (1e-6, "m"),
    # area / volume
    "m²": (1.0, "m²"), "m^2": (1.0, "m²"), "mm²": (1e-6, "m²"), "mm^2": (1e-6, "m²"), "cm²": (1e-4, "m²"),
    "m³": (1.0, "m³"), "m^3": (1.0, "m³"), "mm³": (1e-9, "m³"), "mm^3": (1e-9, "m³"), "cm³": (1e-6, "m³"),
    "L": (1e-3, "m³"), "l": (1e-3, "m³"), "dm³": (1e-3, "m³"),
    # time
    "s": (1.0, "s"), "ms": (1e-3, "s"), "min": (60.0, "s"), "h": (3600.0, "s"),
    # force / power / energy
    "N": (1.0, "N"), "kN": (1e3, "N"), "W": (1.0, "W"), "kW": (1e3, "W"), "J": (1.0, "J"), "kJ": (1e3, "J"),
    "Wh": (3600.0, "J"), "kWh": (3.6e6, "J"),
    # electrical
    "V": (1.0, "V"), "mV": (1e-3, "V"), "kV": (1e3, "V"), "A": (1.0, "A"), "mA": (1e-3, "A"), "Ah": (3600.0, "C"),
    "Ω": (1.0, "Ω"), "ohm": (1.0, "Ω"),
    # other
    "Pa": (1.0, "Pa"), "kPa": (1e3, "Pa"), "MPa": (1e6, "Pa"), "bar": (1e5, "Pa"),
    "rad": (1.0, "rad"), "deg": (0.017453292519943295, "rad"), "°": (0.017453292519943295, "rad"),
    "K": (1.0, "K"), "Hz": (1.0, "Hz"), "rpm": (1 / 60, "Hz"),
    "m/s": (1.0, "m/s"), "km/h": (1 / 3.6, "m/s"), "kg/m³": (1.0, "kg/m³"), "kg/m^3": (1.0, "kg/m³"),
    "%": (0.01, "1"), "one": (1.0, "1"),
}

# long names used by the SysML v2 ISQ/SI libraries -> symbol
_NAMES = {
    "kilogram": "kg", "gram": "g", "tonne": "t", "metre": "m", "meter": "m", "millimetre": "mm", "millimeter": "mm",
    "centimetre": "cm", "centimeter": "cm", "kilometre": "km", "kilometer": "km", "second": "s", "minute": "min",
    "hour": "h", "newton": "N", "watt": "W", "kilowatt": "kW", "joule": "J", "volt": "V", "ampere": "A",
    "pascal": "Pa", "radian": "rad", "degree": "deg", "kelvin": "K", "hertz": "Hz", "litre": "L", "liter": "L",
}


def normalise_symbol(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = unit.strip()
    return _NAMES.get(u.lower(), u)


def to_si(value, unit: str | None) -> tuple[float | None, str | None]:
    """Return (value in SI, SI unit symbol). (None, None) if value not numeric or unit unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, None
    if unit is None:
        return float(value), None
    sym = normalise_symbol(unit)
    if sym == "°C" or sym == "degC":
        return float(value) + 273.15, "K"
    if sym in _UNITS:
        f, si = _UNITS[sym]
        return float(f"{float(value) * f:.12g}"), si   # 700 mm -> 0.7 m, not 0.7000000000000001
    return None, None


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between two units of the same dimension, e.g. convert(1200, 'g', 'kg') == 1.2."""
    v_si, si_a = to_si(value, from_unit)
    one_si, si_b = to_si(1.0, to_unit)
    if v_si is None or one_si is None or si_a != si_b:
        raise ValueError(f"cannot convert {from_unit!r} to {to_unit!r}")
    return float(f"{v_si / one_si:.12g}")   # drop float noise such as 11.200000000000001
