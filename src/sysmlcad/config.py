"""Umgebungsabhaengige Adressen an genau einer Stelle.

Im Devcontainer zeigt SYSML_API_URL auf den Servicenamen sysml-api,
auf dem Host auf localhost. Kein Code darunter kennt den Unterschied.
"""

import os

SYSML_API_URL = os.environ.get("SYSML_API_URL", "http://localhost:9000")
