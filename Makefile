# In the devcontainer the virtualenv is already on PATH; on the host it is .venv/
PY     := $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python)
PIP    := $(shell test -x .venv/bin/pip    && echo .venv/bin/pip    || echo pip)
PYTEST := $(shell test -x .venv/bin/pytest && echo .venv/bin/pytest || echo pytest)
export PYTHONPATH := src:cad

# In the devcontainer the Compose overlay sets SYSML_API_URL to http://sysml-api:9000
API_URL := $(or $(SYSML_API_URL),http://localhost:9000)

# --env-file is MANDATORY: otherwise Compose looks for .env in the directory of
# the first -f file (docker/), not in the project root. Without the flag,
# interpolation of PLAY_SECRET fails.
COMPOSE := docker compose --env-file .env \
             -f docker/docker-compose.yml \
             -f .devcontainer/docker-compose.dev.yml

.PHONY: help venv secret vendor up api jupyter down logs api-docs \
        cad verify verify-api test clean

help:
	@echo "In the devcontainer:  cad  verify  verify-api  test  clean"
	@echo "On the host:          secret  vendor  api  jupyter  logs  down  up"

# ---------------------------------------------------------------- devcontainer

cad:
	$(PY) cad/motor_housing.py

verify:
	$(PY) -m sysmlcad.verify

verify-api:
	$(PY) -m sysmlcad.verify api

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
	@test -f .env && echo ".env already exists -- left untouched" || \
	  ( echo "PLAY_SECRET=$$(head -c 48 /dev/urandom | base64 | tr -d '\n')" > .env \
	    && echo ".env created" )
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
