"""A single unit registry for the whole project.

Two registries in one process produce quantities pint refuses to compare --
a mistake that only surfaces late, at the moment a verdict is computed.
"""

import pint

ureg = pint.UnitRegistry()
Q = ureg.Quantity
