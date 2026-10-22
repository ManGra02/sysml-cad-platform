#!/bin/sh
# The SysML kernel does NOT read ISYSML_API_BASE_PATH from the process environment,
# only from the env block of its own kernel.json. Without this, %publish quietly
# posts to the public community server (sysml2.intercax.com) instead of Flexo.
# Written at every start, so the target can be changed in docker-compose.yml.
set -e
python - <<'EOF'
import json, os, pathlib
p = pathlib.Path("/opt/conda/share/jupyter/kernels/sysml/kernel.json")
d = json.loads(p.read_text())
d.setdefault("env", {}).update({
    "ISYSML_API_BASE_PATH": os.environ["ISYSML_API_BASE_PATH"],
    "ISYSML_LIBRARY_PATH": os.environ.get("ISYSML_LIBRARY_PATH", "/opt/sysml.library"),
})
p.write_text(json.dumps(d, indent=2))
print("sysml kernel publishes to", os.environ["ISYSML_API_BASE_PATH"])
EOF
exec "$@"
