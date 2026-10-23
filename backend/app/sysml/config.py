"""Where the SysML v2 repository is.

The backend talks to a SysML v2 API server (Flexo MMS: flexo-mms-sysmlv2) over
plain HTTP. Like the bridge, the repository is a service that comes and goes:
"not reachable" is a normal state, reported by /api/sysml/status -- everything
that does not need SysML keeps working.

Overrides via environment variables:
  SYSML_API_URL       base URL of the SysML v2 API   (default http://127.0.0.1:8083,
                      the port of flexo/docker-compose.yml)
  SYSML_API_TOKEN     bearer token, optional -- flexo-sysmlv2 falls back to its
                      own FLEXO_AUTH when the request carries none
  SYSML_TIMEOUT_S     timeout per request in seconds (default 60; Flexo is slow
                      on the first write after start)
  FLEXO_LAYER1_URL    Flexo layer1, only for the one-time `setup-org`
                      (default http://127.0.0.1:8080)
  FLEXO_SYSMLV2_ORG   the org the SysML v2 service writes into (default sysmlv2)
  SYSML_KERNEL_URL    Jupyter with the SysML v2 Pilot kernel, parses .sysml files for the
                      import (default http://127.0.0.1:8888, the `import` profile of
                      flexo/docker-compose.yml)
  SYSML_KERNEL_TOKEN  its Jupyter token (default sysmlcad, as in the compose file)
  SYSML_KERNEL_TARGET where the kernel's %publish posts to, as the KERNEL names it
                      (default http://flexo-sysmlv2:8080 -- Flexo inside the compose network)
"""

import os
from dataclasses import dataclass
from pathlib import Path

from app.config import read_env_file  # noqa: F401  (re-exported for app.sysml.__main__)

#: flexo/ in the repository root: docker-compose.yml and its env files
FLEXO_DIR = Path(__file__).resolve().parents[3] / "flexo"


@dataclass
class SysmlConfig:
    api_url: str = "http://127.0.0.1:8083"
    token: str | None = None
    timeout_s: float = 60.0
    layer1_url: str = "http://127.0.0.1:8080"
    org: str = "sysmlv2"
    kernel_url: str = "http://127.0.0.1:8888"
    kernel_token: str = "sysmlcad"
    kernel_target: str = "http://flexo-sysmlv2:8080"

    @classmethod
    def from_env(cls):
        return cls(
            api_url=os.environ.get("SYSML_API_URL", cls.api_url).rstrip("/"),
            token=os.environ.get("SYSML_API_TOKEN") or None,
            timeout_s=float(os.environ.get("SYSML_TIMEOUT_S", cls.timeout_s)),
            layer1_url=os.environ.get("FLEXO_LAYER1_URL", cls.layer1_url).rstrip("/"),
            org=os.environ.get("FLEXO_SYSMLV2_ORG", cls.org),
            kernel_url=os.environ.get("SYSML_KERNEL_URL", cls.kernel_url).rstrip("/"),
            kernel_token=os.environ.get("SYSML_KERNEL_TOKEN", cls.kernel_token),
            kernel_target=os.environ.get("SYSML_KERNEL_TARGET", cls.kernel_target).rstrip("/"),
        )

