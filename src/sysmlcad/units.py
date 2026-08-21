"""Eine einzige Unit-Registry fuer das gesamte Projekt.

Zwei Registries im selben Prozess erzeugen Quantities, die pint nicht
miteinander vergleichen kann -- ein Fehler, der erst spaet auffaellt.
"""

import pint

ureg = pint.UnitRegistry()
Q = ureg.Quantity
