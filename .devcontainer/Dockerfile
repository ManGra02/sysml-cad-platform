# Development image of the platform: Debian 13 (trixie), uv with its own
# Pythons, Node from the devcontainer feature (devcontainer.json).
#
# Generic on purpose. A sub-project that needs more (system libraries, another
# Python) says so in its own Compose overlay via the build args below -- it
# does not edit this file. bidirectional-sync does exactly that:
# bidirectional-sync/.devcontainer/docker-compose.dev.yml.
FROM mcr.microsoft.com/devcontainers/base:trixie

ARG EXTRA_APT_PACKAGES=""
RUN if [ -n "${EXTRA_APT_PACKAGES}" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ${EXTRA_APT_PACKAGES} \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /usr/local/bin/

# Pythons live in the image, not in the user's home: `uv sync` after a rebuild
# must not download them again. 3.11 is the backend's (pinned like FreeCAD's
# bundled Python, see backend/pyproject.toml).
#   UV_LINK_MODE=copy   the uv cache is a volume, the venvs are on the bind
#                       mount -- hardlinks across the two cannot work.
#   --no-bin            no python3.x shims in root's ~/.local/bin; every
#                       project runs through its own venv (uv run, .venv/).
ARG EXTRA_PYTHON_VERSIONS=""
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_LINK_MODE=copy
RUN uv python install --no-bin 3.11 ${EXTRA_PYTHON_VERSIONS} \
 && chown -R vscode:vscode /opt/uv

# Mount points of the cache volumes (docker-compose.yml). A fresh named volume
# takes over owner and mode of the image's directory -- without these lines it
# would belong to root and every `uv sync` / `pnpm install` would fail.
RUN mkdir -p /home/vscode/.cache/uv /home/vscode/.local/share/pnpm \
 && chown -R vscode:vscode /home/vscode/.cache /home/vscode/.local
