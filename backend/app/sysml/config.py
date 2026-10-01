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
"""

import os
from dataclasses import dataclass
from pathlib import Path

#: flexo/ in the repository root: docker-compose.yml and its env files
FLEXO_DIR = Path(__file__).resolve().parents[3] / "flexo"


@dataclass
class SysmlConfig:
    api_url: str = "http://127.0.0.1:8083"
    token: str | None = None
    timeout_s: float = 60.0
    layer1_url: str = "http://127.0.0.1:8080"
    org: str = "sysmlv2"

    @classmethod
    def from_env(cls):
        return cls(
            api_url=os.environ.get("SYSML_API_URL", cls.api_url).rstrip("/"),
            token=os.environ.get("SYSML_API_TOKEN") or None,
            timeout_s=float(os.environ.get("SYSML_TIMEOUT_S", cls.timeout_s)),
            layer1_url=os.environ.get("FLEXO_LAYER1_URL", cls.layer1_url).rstrip("/"),
            org=os.environ.get("FLEXO_SYSMLV2_ORG", cls.org),
        )


def read_env_file(path):
    """KEY=VALUE lines (optional quotes) -> dict. Missing file -> {}."""
    values = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values
