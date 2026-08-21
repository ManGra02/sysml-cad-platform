# 3.14 auf Debian 13 (trixie). Geprueft am 2026-08-21:
# cadquery-ocp-novtk 7.9.3.1.1 liefert cp314-Wheels als manylinux_2_31,
# trixie bringt glibc 2.41 mit -- passt. build123d erlaubt >=3.10,<3.15.
# Fuer reproduzierbare Builds statt dessen den versionierten Tag pinnen,
# z.B. mcr.microsoft.com/devcontainers/python:3.1.5-3.14-trixie
FROM mcr.microsoft.com/devcontainers/python:3.14-trixie

# OCP (die OpenCascade-Bindings hinter build123d) linkt hart gegen libGL.so.1,
# libGLX.so.0 und libX11 -- auch wenn nie ein Fenster geoeffnet wird.
# Ohne diese Pakete scheitert bereits "import build123d".
# libgl1 (libglvnd) reicht: es geht nur um die Symbolaufloesung beim Laden,
# nicht ums Rendern. Einen Mesa-Treiber braucht headless niemand.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libx11-6 \
        libxau6 \
        libxdmcp6 \
        libxext6 \
        libxrender1 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Das venv liegt bewusst AUSSERHALB des Bind-Mounts. cadquery-ocp-novtk ist
# allein ~68 MB Wheel und deutlich mehr entpackt; im gemounteten Workspace
# waere es bei jedem Rebuild neu zu installieren und wuerde auf macOS/Windows
# durch den Dateisystem-Layer ausgebremst.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV && chown -R vscode:vscode $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# ENV allein reicht NICHT: VS Code ermittelt die Umgebung per Login-Shell
# (userEnvProbe). Die vscode-Standardshell ist zsh, und deren Startdateien
# setzen PATH neu -- dabei faellt /opt/venv/bin raus.
RUN echo 'export PATH="/opt/venv/bin:$PATH"' > /etc/profile.d/10-venv.sh \
 && echo 'export PATH="/opt/venv/bin:$PATH"' >> /home/vscode/.bashrc \
 && echo 'export PATH="/opt/venv/bin:$PATH"' >> /home/vscode/.zshrc

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r /tmp/requirements.txt

USER vscode
