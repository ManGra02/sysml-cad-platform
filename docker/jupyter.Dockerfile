# SysML v2 kernel for Jupyter. The official installation is conda-based
# (install/jupyter/install.sh in the SysML-v2-Release repo), hence miniforge
# rather than a Python image.
#
# Restored from commit dde4b82; it was deleted by mistake in f3e8e18 alongside
# the api-services Dockerfile, which the hni-ase fork legitimately replaced.
# docker-compose.yml still references this file, so `make jupyter` and
# `make up` fail without it.
FROM condaforge/miniforge3:latest

# Version taken from install.sh in the release repo. Bump both together.
ARG SYSML_VERSION=0.60.1

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
 && git clone --depth 1 https://github.com/Systems-Modeling/SysML-v2-Release.git /tmp/release \
 && cp -r /tmp/release/sysml.library /opt/sysml.library \
 && rm -rf /tmp/release && apt-get purge -y git && rm -rf /var/lib/apt/lists/*

ENV ISYSML_LIBRARY_PATH=/opt/sysml.library

ARG API_BASE=http://sysml-api:9000

# CRITICAL: the kernel does NOT read ISYSML_API_BASE_PATH from the process
# environment, it reads it from the env block of its own kernel.json. Without
# this patch, %publish quietly publishes to the public community server
# sysml2.intercax.com instead of the local one.
RUN python -c "import json,pathlib; \
p=pathlib.Path('/opt/conda/share/jupyter/kernels/sysml/kernel.json'); \
d=json.loads(p.read_text()); \
d.setdefault('env',{}).update({'ISYSML_API_BASE_PATH':'${API_BASE}','ISYSML_LIBRARY_PATH':'/opt/sysml.library'}); \
p.write_text(json.dumps(d,indent=2))" \
 && cat /opt/conda/share/jupyter/kernels/sysml/kernel.json

# Deliberately NOT installed: the JupyterLab extension
# @systems-modeling/jupyterlab-sysml. It installs via `jupyter labextension
# install`, the deprecated build path under JupyterLab 4, and usually fails.
# It only adds syntax highlighting -- the kernel runs fine without it.

WORKDIR /work
EXPOSE 8888

CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", \
     "--no-browser", "--allow-root", "--notebook-dir=/work"]
