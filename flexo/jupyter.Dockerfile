# SysML v2 Pilot kernel for Jupyter -- the parser behind `python -m app.sysml import-sysml`.
#
# The backend sends a .sysml text to this kernel and then `%publish <Package>`; the kernel
# parses it, resolves names and the standard library (ISQ, SI, ...) and posts the result as
# a commit to the SysML v2 API -- Flexo. Flexo itself cannot read textual notation.
#
# Taken from bidirectional-sync/docker/jupyter.Dockerfile (Vincent Hey, branch
# merge/bidirectional-sync), with one change: the publish target is written into
# kernel.json at container start (jupyter-entrypoint.sh) instead of being baked in.
#
# The official installation is conda-based (install/jupyter/install.sh in the
# SysML-v2-Release repo), hence miniforge rather than a Python image.
FROM condaforge/miniforge3:latest

# Kernel version and the release tag whose install/jupyter/install.sh names it --
# the standard library below comes from that tag. Bump both together.
ARG SYSML_VERSION=0.60.1
ARG SYSML_RELEASE=2026-05

# The kernel is a JVM application and requires Java >= 21.
RUN conda install -y -c conda-forge \
      "jupyter-sysml-kernel=${SYSML_VERSION}" \
      "python=3.12" \
      "jupyterlab=4.*" \
      "graphviz=2.*" \
      "openjdk>=21" \
 && conda clean -afy

# The standard library (ISQ, SI, ...) does not ship with the kernel package,
# it lives in the release repo. Without it, every `import ISQ::*` fails.
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && git clone --depth 1 --branch "${SYSML_RELEASE}" https://github.com/Systems-Modeling/SysML-v2-Release.git /tmp/release \
 && cp -r /tmp/release/sysml.library /opt/sysml.library \
 && rm -rf /tmp/release && apt-get purge -y git && rm -rf /var/lib/apt/lists/*

ENV ISYSML_LIBRARY_PATH=/opt/sysml.library
# Where %publish posts to. Overridden by docker-compose.yml.
ENV ISYSML_API_BASE_PATH=http://flexo-sysmlv2:8080

COPY jupyter-entrypoint.sh /usr/local/bin/jupyter-entrypoint.sh
RUN chmod +x /usr/local/bin/jupyter-entrypoint.sh

WORKDIR /work
EXPOSE 8888

ENTRYPOINT ["/usr/local/bin/jupyter-entrypoint.sh"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--notebook-dir=/work"]
