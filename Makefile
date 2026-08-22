# Im Devcontainer liegt das venv auf dem PATH, auf dem Host unter .venv/
PY := $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python)
PIP := $(shell test -x .venv/bin/pip && echo .venv/bin/pip || echo pip)
PYTEST := $(shell test -x .venv/bin/pytest && echo .venv/bin/pytest || echo pytest)
export PYTHONPATH := src:cad
# Im Devcontainer setzt das Compose-Overlay SYSML_API_URL auf http://sysml-api:9000
API_URL := $(or $(SYSML_API_URL),http://localhost:9000)

.PHONY: venv vendor up api jupyter down logs api-docs cad verify test clean

# NUR fuer die Arbeit ohne Devcontainer. Im Devcontainer liegt das venv
# bereits im Image unter /opt/venv -- dieses Ziel dort NICHT aufrufen.
venv:
	python3 -m venv .venv && $(PIP) install -U pip && $(PIP) install -r requirements.txt

vendor:
	test -d vendor/SysML-v2-API-Services || \
	  git clone https://github.com/hni-ase/SysML-v2-API-Services.git vendor/SysML-v2-API-Services
	@# hbm2ddl ist im Fork NICHT per Env konfigurierbar und steht auf create-drop.
	@# Ohne diesen Patch wird das Schema bei jedem sauberen Stop geloescht.
	@sed -i 's|"hibernate.hbm2ddl.auto" value="create-drop"|"hibernate.hbm2ddl.auto" value="update"|' \
	  vendor/SysML-v2-API-Services/conf/META-INF/persistence.xml
	@grep -n hbm2ddl vendor/SysML-v2-API-Services/conf/META-INF/persistence.xml

COMPOSE := docker compose --env-file .env -f docker/docker-compose.yml -f .devcontainer/docker-compose.dev.yml

up: vendor
	$(COMPOSE) up -d --build

api: vendor
	$(COMPOSE) up -d --build sysml-api

jupyter:
	$(COMPOSE) up -d --build jupyter
	@echo "JupyterLab: http://localhost:8888/?token=sysmlcad"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f sysml-api

api-docs:
	@echo "Swagger: $(API_URL)/docs/  (erster Aufruf initialisiert das Schema)"
	@curl -sS -o /dev/null -w "HTTP %{http_code}\n" $(API_URL)/docs/ || true

cad:
	$(PY) cad/motor_housing.py

verify:
	$(PY) -m sysmlcad.verify

test:
	$(PYTEST)

clean:
	rm -rf out/*.step out/*.xml .pytest_cache **/__pycache__
