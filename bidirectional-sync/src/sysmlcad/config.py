"""Environment-dependent addresses, in exactly one place.

Inside the devcontainer SYSML_API_URL points at the service name sysml-api;
on the host it points at localhost. No code below this line knows the
difference.
"""

import os

SYSML_API_URL = os.environ.get("SYSML_API_URL", "http://localhost:9000")
