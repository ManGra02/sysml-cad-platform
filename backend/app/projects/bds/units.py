"""One pint registry for the whole module.

Two registries in one process produce quantities pint refuses to compare --
a mistake that only surfaces at the moment a verdict is computed.
"""

import pint

ureg = pint.UnitRegistry()
Q = ureg.Quantity


def fmt(quantity):
    """Quantity -> short text ("100 mm"), the same everywhere a number is shown."""
    return None if quantity is None else "%s" % format(quantity, ".6g~P")


def as_json(quantity):
    """Quantity -> {value, unit, text} for HTTP responses."""
    if quantity is None:
        return None
    return {"value": float(quantity.magnitude), "unit": format(quantity.units, "~P"),
            "text": fmt(quantity)}
