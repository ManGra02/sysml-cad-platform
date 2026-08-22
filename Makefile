# Im Devcontainer liegt das venv auf dem PATH, auf dem Host unter .venv/
PY     := $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python)
PIP    := $(shell test -x .venv/bin/pip    && echo .venv/bin/pip    || echo pip)
PYTEST := $(shell test -x .venv/bin/pytest && echo .venv/bin/pytest || echo pytest)
export PYTHONPATH := src:cad

# Im Devcontainer setzt das Compose-Overlay SYSML_API_URL auf http://sysml-api:9000
API_URL := $(or $(SYSML_API_URL),http://localhost:9000)

# --env-file ist PFLICHT: Compose sucht die .env sonst im Verzeichnis der ersten
# -f-Datei (docker/), nicht im Projektwurzelverzeichnis. Ohne das Flag scheitert
# die Interpolation von PLAY_SECRET.
COMPOSE := docker compose --env-file .env \
             -f docker/docker-compose.yml \
             -f .devcontainer/docker-compose.dev.yml

.PHONY: help venv secret vendor up api jupyter down logs api-docs \
        cad verify verify-api test clean

help:
	@echo "Im Devcontainer:  cad  verify  verify-api  test  clean"
	@echo "Auf dem Host:     secret  vendor  api  jupyter  logs  down  up"

# ---------------------------------------------------------------- Devcontainer

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

# NUR fuer die Arbeit ohne Devcontainer. Im Devcontainer liegt das venv
# bereits im Image unter /opt/venv -- dieses Ziel dort NICHT aufrufen.
venv:
	python3 -m venv .venv && $(PIP) install -U pip && $(PIP) install -r requirements.txt

# ----------------------------------------------------------------------- Host

# Play verweigert im Produktionsmodus den Start ohne ausreichend langen Secret-Key.
secret:
	@test -f .env && echo ".env existiert bereits -- nichts geaendert" || \
	  ( echo "PLAY_SECRET=$$(head -c 48 /dev/urandom | base64 | tr -d '\n')" > .env \
	    && echo ".env angelegt" )
	@grep -q '^\.env$$' .gitignore || echo ".env" >> .gitignore

vendor:
	test -d vendor/SysML-v2-API-Services || \
	  git clone https://github.com/hni-ase/SysML-v2-API-Services.git vendor/SysML-v2-API-Services
	@# hbm2ddl ist im Fork NICHT per Env konfigurierbar und steht auf create-drop.
	@# Ohne diesen Patch wird das Schema bei jedem sauberen Stop geloescht.
	@sed -i 's|"hibernate.hbm2ddl.auto" value="create-drop"|"hibernate.hbm2ddl.auto" value="update"|' \
	  vendor/SysML-v2-API-Services/conf/META-INF/persistence.xml
	@grep -n hbm2ddl vendor/SysML-v2-API-Services/conf/META-INF/persistence.xml

api: secret vendor
	$(COMPOSE) up -d --build sysml-api
	@echo "Bereit, wenn 'Listening for HTTP' im Log steht:  make logs"

jupyter:
	$(COMPOSE) up -d --build jupyter
	@echo "JupyterLab: http://localhost:8888/?token=sysmlcad"

# ACHTUNG: startet ALLES inklusive dev und jupyter. Im Devcontainer-Workflow
# nicht noetig -- dort genuegt 'make api'.
up: secret vendor
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f sysml-api

# Swagger-Oberflaeche. Das Schema entsteht im Produktionsmodus beim Serverstart,
# NICHT beim ersten Aufruf dieser Seite (das galt fuer den alten sbt-run-Modus).
api-docs:
	@echo "Swagger: $(API_URL)/docs/"
	@curl -sS -o /dev/null -w "HTTP %{http_code}\n" $(API_URL)/docs/ || true
