# SysML-v2-Kernel fuer Jupyter. Die offizielle Installation ist conda-basiert
# (install/jupyter/install.sh im SysML-v2-Release-Repo), deshalb miniforge
# statt eines Python-Images.
FROM condaforge/miniforge3:latest

# Version aus install.sh des Release-Repos. Bei einem Update dort nachziehen.
ARG SYSML_VERSION=0.60.1

# Der Kernel selbst ist eine JVM-Anwendung und verlangt Java >= 21.
RUN conda install -y -c conda-forge \
      "jupyter-sysml-kernel=${SYSML_VERSION}" \
      "python=3.12" \
      "jupyterlab=4.*" \
      "graphviz=2.*" \
      "openjdk>=21" \
 && conda clean -afy


# Die Standardbibliothek (ISQ, SI, ...) liegt nicht im Kernel-Paket, sondern
# im Release-Repo. Ohne sie scheitert jedes "import ISQ::*".
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && git clone --depth 1 https://github.com/Systems-Modeling/SysML-v2-Release.git /tmp/release \
 && cp -r /tmp/release/sysml.library /opt/sysml.library \
 && rm -rf /tmp/release && apt-get purge -y git && rm -rf /var/lib/apt/lists/*

ENV ISYSML_LIBRARY_PATH=/opt/sysml.library


ARG API_BASE=http://sysml-api:9000

# Der Kernel liest ISYSML_API_BASE_PATH NICHT aus der Prozessumgebung, sondern
# aus dem env-Block seiner kernel.json. Ohne diesen Eintrag publiziert %publish
# auf den oeffentlichen Server sysml2.intercax.com.
RUN python -c "import json,pathlib; \
p=pathlib.Path('/opt/conda/share/jupyter/kernels/sysml/kernel.json'); \
d=json.loads(p.read_text()); \
d.setdefault('env',{}).update({'ISYSML_API_BASE_PATH':'${API_BASE}','ISYSML_LIBRARY_PATH':'/opt/sysml.library'}); \
p.write_text(json.dumps(d,indent=2))" \
 && cat /opt/conda/share/jupyter/kernels/sysml/kernel.json
 

# Bewusst NICHT installiert: die JupyterLab-Extension
# @systems-modeling/jupyterlab-sysml. Sie wird per "jupyter labextension install"
# eingespielt, was unter JupyterLab 4 der veraltete Build-Pfad ist und meist
# scheitert. Sie liefert nur Syntax-Highlighting -- der Kernel laeuft ohne sie.

WORKDIR /work
EXPOSE 8888

CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", \
     "--no-browser", "--allow-root", "--notebook-dir=/work"]
