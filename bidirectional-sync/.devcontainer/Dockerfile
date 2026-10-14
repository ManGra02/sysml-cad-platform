# 3.14 on Debian 13 (trixie). Checked 2026-08-21:
# cadquery-ocp-novtk 7.9.3.1.1 ships cp314 wheels as manylinux_2_31 and trixie
# carries glibc 2.41 -- they match. build123d allows >=3.10,<3.15.
# For reproducible builds, pin the versioned tag instead, e.g.
# mcr.microsoft.com/devcontainers/python:3.1.5-3.14-trixie
FROM mcr.microsoft.com/devcontainers/python:3.14-trixie

# OCP (the OpenCascade bindings behind build123d) links hard against
# libGL.so.1, libGLX.so.0 and libX11 -- even when no window is ever opened.
# Without these packages even "import build123d" fails.
# libgl1 (libglvnd) is enough: this is only about resolving symbols at load
# time, not about rendering. Headless needs no Mesa driver.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libx11-6 \
        libxau6 \
        libxdmcp6 \
        libxext6 \
        libxrender1 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# The virtualenv deliberately lives OUTSIDE the bind mount. cadquery-ocp-novtk
# alone is a ~68 MB wheel and considerably more unpacked; inside the mounted
# workspace it would be reinstalled on every rebuild and slowed down by the
# filesystem layer on macOS and Windows.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV && chown -R vscode:vscode $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# ENV alone is NOT enough: VS Code probes the environment through a login
# shell (userEnvProbe). The vscode default shell is zsh, and its startup files
# rebuild PATH from scratch -- which drops /opt/venv/bin.
RUN echo 'export PATH="/opt/venv/bin:$PATH"' > /etc/profile.d/10-venv.sh \
 && echo 'export PATH="/opt/venv/bin:$PATH"' >> /home/vscode/.bashrc \
 && echo 'export PATH="/opt/venv/bin:$PATH"' >> /home/vscode/.zshrc

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r /tmp/requirements.txt

USER vscode
