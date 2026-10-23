# Shortcuts for the platform and its BDS module (Bi-Directional Synchronization).
#
# BDS is no longer a CLI of its own (the bidirectional-sync PoC's Makefile): it runs
# inside the backend, so every BDS target below is a request to the RUNNING backend
# (`make dev` or `make start` in a second terminal). The targets keep the PoC's names.
#
#   make bds-setup                  once per Flexo start: org + the BDS example models
#   make verify                     the default workspace
#   make verify WS=<name>           another one (data/bds/<name>/)
#   make workspaces                 what exists
#
# Works the same natively, in the devcontainer and in its Linux variant: the backend
# is on 127.0.0.1:8000 in all three (and the sysml CLI reads SYSML_API_URL itself).

SHELL       := /bin/bash
.SHELLFLAGS := -o pipefail -c

# One workspace = one SysML project + one FreeCAD document + the mapping between them.
WS  ?= Gearbox
API ?= http://127.0.0.1:8000/api/projects/bds
# jq filter for every response; e.g. `make verify JQ=.summary`
JQ  ?= .

WSURL := $(API)/workspaces/$(WS)
GET   := curl -sS --fail-with-body
POST  := curl -sS --fail-with-body -X POST -H 'Content-Type: application/json'
SYSML := uv run --directory backend python -m app.sysml
# `AI=1` (or AI=ai) means the Ollama proposer, otherwise the stdlib baseline.
PROPOSER := $(if $(AI),ai,difflib)

# The BDS example models: <Flexo project name>:<file under data/examples/sysml/bds/>.
BDS_MODELS := Gearbox:gearbox.json MotorHousing:motor_housing.json CubeFreecad:cube.json

.PHONY: help dev start test status flexo-setup bds-models bds-setup \
        workspaces workspace catalog mapping gates propose proposals confirm reject \
        propose-score verify verify-last sync-limits freecad-health

help:
	@echo "Platform:          dev  start  test  status"
	@echo "Flexo (once/start): bds-setup  (= flexo-setup + bds-models)"
	@echo "BDS (WS=$(WS)):     workspaces  workspace  catalog  mapping  gates"
	@echo "Mapping proposals: propose [AI=1] [TOP=n] [DRY=1]  proposals  propose-score [AI=1]"
	@echo "                   confirm ID=p-01 [REQ=<requirement>]  reject ID=p-01 [REASON=...]"
	@echo "Verification:      verify  verify-last  sync-limits [APPLY=1]  freecad-health"
	@echo "Output filter:     JQ=<jq filter>, e.g. make verify JQ=.summary"

# ------------------------------------------------------------------- platform

# Backend --reload --dev + Vite (http://127.0.0.1:5173). Blocks; BDS targets in another terminal.
dev:
	bash scripts/dev.sh

# Backend with the built UI (http://127.0.0.1:8000).
start:
	bash scripts/start.sh --no-browser

test:
	cd backend && uv run pytest

status:
	@$(SYSML) status
	@$(GET) http://127.0.0.1:8000/api/status | jq . || echo "backend not running -> make dev"

# --------------------------------------------------------------------- flexo

# Flexo keeps its database in memory: after every start of its containers, run
# bds-setup again. Both steps are safe to repeat.
flexo-setup:
	$(SYSML) setup-org || true

# Creates each example project once (a second create-project would make a
# second project with the same name) and commits the model into it.
bds-models:
	@for entry in $(BDS_MODELS); do \
	  name=$${entry%%:*}; file=$${entry#*:}; \
	  if ($(SYSML) projects) | grep -qw "$$name"; then \
	    echo "$$name: already in Flexo -- left untouched"; \
	  else \
	    ($(SYSML) create-project "$$name" && \
	     $(SYSML) load-file "$$name" ../data/examples/sysml/bds/$$file) || exit 1; \
	  fi; \
	done

bds-setup: flexo-setup bds-models

# ----------------------------------------------------------------------- BDS

workspaces:
	@$(GET) $(API)/workspaces | jq '$(JQ)'

workspace:
	@$(GET) $(WSURL) | jq '$(JQ)'

# What exists on each side: SysML parts, attributes and requirements; CAD objects,
# the measurements they support and their parameters. Reads Flexo and FreeCAD.
catalog:
	@$(GET) $(WSURL)/catalog | jq '$(JQ)'

mapping:
	@$(GET) $(WSURL)/mapping | jq '$(JQ)'

# Is the MAPPING sound: existence, dimension, uniqueness, plausibility.
# A different question from `verify`.
gates:
	@$(GET) $(WSURL)/gates | jq '$(JQ)'

# Suggest mapping entries. Nothing is applied: candidates land in proposals.yaml
# with status `proposed` and reach mapping.yaml only through `confirm`.
propose:
	@$(POST) $(WSURL)/proposals \
	  -d "$$(jq -nc --arg p '$(PROPOSER)' --argjson top '$(or $(TOP),1)' --argjson dry '$(if $(DRY),true,false)' \
	         '{proposer: $$p, top: $$top, dry_run: $$dry}')" | jq '$(JQ)'

# Stored proposals, the pending ones gated against the mapping as it is now.
proposals:
	@$(GET) '$(WSURL)/proposals?check=true' | jq '$(JQ)'

# Re-gates, then writes into mapping.yaml. Without REQ the entry is linked to no
# requirement and a run never uses it.   make confirm ID=p-01 REQ=MaxLength
confirm:
	@test -n "$(ID)" || { echo "usage: make confirm ID=p-01 [REQ=<requirement>]" >&2; exit 2; }
	@$(POST) $(WSURL)/proposals/$(ID)/confirm \
	  -d "$$(jq -nc --arg r '$(REQ)' 'if $$r == "" then {} else {requirement: $$r} end')" | jq '$(JQ)'

reject:
	@test -n "$(ID)" || { echo "usage: make reject ID=p-01 [REASON=...]" >&2; exit 2; }
	@$(POST) $(WSURL)/proposals/$(ID)/reject \
	  -d "$$(jq -nc --arg r '$(REASON)' '{reason: $$r}')" | jq '$(JQ)'

# How good is a proposer, against data/bds/<WS>/gold_mapping.yaml.
propose-score:
	@$(GET) '$(WSURL)/score?proposer=$(PROPOSER)' | jq '$(JQ)'

# Requirements against the CAD geometry -> verdicts and gaps (stored as last_run.json).
verify:
	@$(POST) $(WSURL)/verify -d '{}' | jq '$(JQ)'

verify-last:
	@$(GET) $(WSURL)/verify/last | jq '$(JQ)'

# Requirement limits into the FreeCAD sheet `SysML`. A dry run unless APPLY=1;
# then one undo step in FreeCAD and a line in sync_log.jsonl.
sync-limits:
	@$(POST) $(WSURL)/sync -d '{"apply": $(if $(APPLY),true,false)}' | jq '$(JQ)'

# Does the backend see the FreeCAD bridge?
freecad-health:
	@$(GET) http://127.0.0.1:8000/api/status | jq '$(if $(filter .,$(JQ)),.bridge // .,$(JQ))'
