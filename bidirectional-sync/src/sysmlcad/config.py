"""Environment-dependent addresses, in exactly one place.

Inside the devcontainer SYSMLCAD_SYSML_API_URL points at the service name
sysml-api; on the host it points at localhost. No code below this line knows
the difference.

SYSMLCAD_SYSML_API_URL first: in the platform's devcontainer SYSML_API_URL is
the platform's own SysML server (Flexo), a different server with a different
API. The plain name still counts when it is the only one set.
"""

import os

SYSML_API_URL = (
    os.environ.get("SYSMLCAD_SYSML_API_URL")
    or os.environ.get("SYSML_API_URL")
    or "http://localhost:9000"
)
