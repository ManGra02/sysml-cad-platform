# In the devcontainer the virtualenv is already on PATH; on the host it is .venv/
PY     := $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python)
PIP    := $(shell test -x .venv/bin/pip    && echo .venv/bin/pip    || echo pip)
PYTEST := $(shell test -x .venv/bin/pytest && echo .venv/bin/pytest || echo pytest)
export PYTHONPATH := src:cad

# In the devcontainer the Compose overlay sets SYSML_API_URL to http://sysml-api:9000
API_URL := $(or $(SYSML_API_URL),http://localhost:9000)

# Which project -- one SysML model and its mapping under projects/<name>/. Every
# verification, gate, catalogue and proposal command works on exactly one.
#   make verify                     the default project
#   make verify PROJECT=gearbox     another one
#   make projects                   what exists
PROJECT ?= motor_housing
P := --project $(PROJECT)

# Compose looks for the env file in the directory of the FIRST -f file (docker/),
# not in the project root. That is why the file lives at docker/.env: the VS Code
# Dev Containers extension builds its own compose command and cannot pass
# --env-file, so it only ever finds the secret at that default location.
# The flag here is redundant but keeps the Makefile working if the -f order changes.
COMPOSE := docker compose --env-file docker/.env \
             -f docker/docker-compose.yml \
             -f .devcontainer/docker-compose.dev.yml

.PHONY: help venv secret vendor up api jupyter down logs api-docs \
        cad verify verify-api test clean step-fixtures explore-cad catalog gates \
        propose proposals confirm propose-score projects publish capture

help:
	@echo "In the devcontainer:  cad  verify  verify-api  gates  test  clean"
	@echo "                      catalog  explore-cad  step-fixtures"
	@echo "Mapping proposals:    propose  proposals  confirm ID=p-01  propose-score"
	@echo "Projects:             projects  publish NB=...  capture   (PROJECT=<name>)"
	@echo "                      (default: $(PROJECT))"
	@echo "On the host:          secret  vendor  api  jupyter  logs  down  up"

# ---------------------------------------------------------------- devcontainer

cad:
	$(PY) cad/motor_housing.py
	$(PY) cad/gearbox.py

# Regenerates fixtures/step/. They are committed, so this is only needed after
# changing a CAD script -- the STEP tests must be able to run without it.
step-fixtures:
	$(PY) cad/export_fixtures.py

# Show what is inside a STEP file: node names, volumes, bounding boxes, and the
# reference strings to paste into mapping.yaml.
#   make explore-cad FILE=fixtures/step/gearbox.step
explore-cad:
	$(PY) -m sysmlcad.explore_cad $(or $(FILE),fixtures/step/gearbox.step)

# What exists on each side: SysML parts and attributes, CAD objects and the
# measurements they support. Reads the project's capture
# (projects/<name>/elements.json), so it needs no server;
# `make catalog SOURCE=api` reads the live one.
catalog:
	$(PY) -m sysmlcad.catalog $(P) $(SOURCE)

projects:
	$(PY) -m sysmlcad.project

# Publish a model without clicking through JupyterLab: runs the notebook's code
# cells on the SysML kernel of the Jupyter container (`make jupyter` first).
#   make publish NB=notebooks/04_publish_box2.ipynb
publish:
	$(PY) -m sysmlcad.publish $(NB)

# Store the server's current state of a project as its offline capture.
#   make capture PROJECT=box2
capture:
	$(PY) -m sysmlcad.explore $(P) && cp out/elements.json projects/$(PROJECT)/elements.json

# Is the MAPPING sound: dimension, existence, uniqueness, plausibility.
# A different question from `verify` -- a correctly mapped part that is too long
# passes here and fails there.
gates:
	$(PY) -m sysmlcad.gates $(P)

# Suggest mapping entries. Nothing is applied: candidates land in
# projects/<name>/proposals.yaml with status `proposed` and reach mapping.yaml
# only through `confirm`. `make propose AI=openai` (or AI=1) asks a language
# model instead of the stdlib baseline: whatever OPENAI_BASE_URL and
# SYSMLCAD_OPENAI_MODEL point at -- needs `pip install openai` and a key.
# `filter-out 1` keeps `AI=1` meaning the default backend rather than a model
# literally named "1".
propose:
	$(PY) -m sysmlcad.propose $(P) $(if $(AI),--ai $(filter-out 1,$(AI)),) $(if $(TOP),--top $(TOP),)

proposals:
	$(PY) -m sysmlcad.propose $(P) --list

# Confirm one: re-gates it, then writes it into mapping.yaml with your name and
# the date.   make confirm ID=p-01
confirm:
	$(PY) -m sysmlcad.confirm $(P) $(ID)

# How good is a proposer, against projects/<name>/gold_mapping.yaml. The number
# to watch is wrong@1, not hit rate.
propose-score:
	$(PY) -m sysmlcad.score $(P) $(if $(AI),--ai $(filter-out 1,$(AI)),)

verify:
	$(PY) -m sysmlcad.verify $(P)

verify-api:
	$(PY) -m sysmlcad.verify $(P) api

test:
	$(PYTEST)

clean:
	rm -rf out/*.step out/*.xml out/*.json .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ONLY for working without the devcontainer. Inside the devcontainer the
# virtualenv already ships in the image at /opt/venv -- do NOT run this there.
venv:
	python3 -m venv .venv && $(PIP) install -U pip && $(PIP) install -r requirements.txt

# ----------------------------------------------------------------------- host

# In production mode, Play refuses to start without a sufficiently long secret key.
secret:
	@test -f docker/.env && echo "docker/.env already exists -- left untouched" || \
	  ( echo "PLAY_SECRET=$$(head -c 48 /dev/urandom | base64 | tr -d '\n')" > docker/.env \
	    && echo "docker/.env created" )
	@grep -q '^\.env$$' .gitignore || echo ".env" >> .gitignore

vendor:
	test -d vendor/SysML-v2-API-Services || \
	  git clone https://github.com/hni-ase/SysML-v2-API-Services.git vendor/SysML-v2-API-Services
	@# In the fork, hbm2ddl is NOT configurable via the environment and is set to
	@# create-drop. Without this patch the schema is dropped on every clean stop.
	@sed -i 's|"hibernate.hbm2ddl.auto" value="create-drop"|"hibernate.hbm2ddl.auto" value="update"|' \
	  vendor/SysML-v2-API-Services/conf/META-INF/persistence.xml
	@grep -n hbm2ddl vendor/SysML-v2-API-Services/conf/META-INF/persistence.xml

api: secret vendor
	$(COMPOSE) up -d --build sysml-api
	@echo "Ready once 'Listening for HTTP' shows up in the log:  make logs"

jupyter:
	$(COMPOSE) up -d --build jupyter
	@echo "JupyterLab: http://localhost:8888/?token=sysmlcad"

# CAUTION: starts EVERYTHING including dev and jupyter. Not needed in the
# devcontainer workflow -- 'make api' is enough there.
up: secret vendor
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f sysml-api

# Swagger UI. In production mode the schema is generated at server start,
# NOT on the first request to this page (that was true for the old sbt run mode).
api-docs:
	@echo "Swagger: $(API_URL)/docs/"
	@curl -sS -o /dev/null -w "HTTP %{http_code}\n" $(API_URL)/docs/ || true
