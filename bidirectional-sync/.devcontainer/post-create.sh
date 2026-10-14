#!/usr/bin/env bash
# bidirectional-sync's part of the platform devcontainer's postCreateCommand
# (called by .devcontainer/post-create.sh at the repository root).
#
# The virtualenv is .venv/ here, which the Makefile picks up on its own
# (PY := .venv/bin/python). Python 3.14 comes from the image -- this
# overlay's EXTRA_PYTHON_VERSIONS -- so nothing is downloaded but the wheels,
# and those come from the uv cache volume after the first time.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv venv --allow-existing --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -c "import build123d, pint; print('build123d', build123d.__version__, '| pint', pint.__version__)"
