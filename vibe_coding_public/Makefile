# vibe_coding top-level orchestrator.
# Wraps cluster lifecycle and per-service operations.

SHELL := /bin/bash
CLUSTER := vibe
NAMESPACE := vibe-coding
SERVICES := $(notdir $(wildcard services/*))
SKILL_SERVICES := $(notdir $(wildcard services_skill/*))

# When invoking per-service targets, caller passes SVC=<id>, e.g.
#   make build SVC=01-catalog-api
# FAULT=<fault-id> for inject, e.g.
#   make inject SVC=01-catalog-api FAULT=F01-pod-kill
SVC ?=
FAULT ?=
PROMPT_VARIANT ?= with-skill

.PHONY: help up down deps wait-deps build deploy wait smoke inject judge cleanup capture demo all list skill-specs skill-materialize skill-strip-faults skill-restore-faults skill-reset-generation skill-generate skill-prepare-workspace skill-generate-isolated skill-import-generated list-skill compare-skill stop-skill-runs build-skill deploy-skill wait-skill smoke-skill inject-skill judge-skill cleanup-skill capture-skill demo-skill all-skill

help: ## show this help
	@echo "vibe_coding — make targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Services (use SVC=<id>): "
	@for s in $(SERVICES); do echo "  $$s"; done

up: ## create kind cluster, install chaos-mesh, apply shared deps
	bash infra/install/up.sh

down: ## delete kind cluster
	bash infra/install/down.sh

deps: ## (re-)apply shared dep manifests (postgres / redis / mock-upstream)
	kubectl apply -f infra/deps/

wait-deps: ## block until postgres, redis-cache, redis-stream, mock-upstream are Ready
	kubectl -n $(NAMESPACE) rollout status deploy/postgres --timeout=180s
	kubectl -n $(NAMESPACE) rollout status deploy/redis-cache --timeout=120s
	kubectl -n $(NAMESPACE) rollout status deploy/redis-stream --timeout=120s
	kubectl -n $(NAMESPACE) rollout status deploy/mock-upstream --timeout=120s

list: ## list available services
	@for s in $(SERVICES); do echo "  $$s"; done

skill-specs: ## extract source-free skill-regeneration specs/prompts (LIMIT=N optional)
	python3 tools/skill_experiment.py extract --prompt-variant $(PROMPT_VARIANT) $(if $(LIMIT),--limit $(LIMIT),) $(if $(SVC),--services $(SVC),)

skill-materialize: ## create services_skill skeletons from extracted specs (LIMIT=N optional)
	python3 tools/skill_experiment.py materialize --prompt-variant $(PROMPT_VARIANT) $(if $(LIMIT),--limit $(LIMIT),) $(if $(SVC),--services $(SVC),)

skill-strip-faults: ## remove services_skill fault manifests before SDK generation
	python3 tools/skill_experiment.py strip-faults $(if $(LIMIT),--limit $(LIMIT),) $(if $(SVC),--services $(SVC),)

skill-restore-faults: ## copy original service fault manifests back before evaluation
	python3 tools/skill_experiment.py restore-faults $(if $(LIMIT),--limit $(LIMIT),) $(if $(SVC),--services $(SVC),)

skill-reset-generation: ## reset services_skill from existing specs and strip faults (no re-extract)
	$(MAKE) skill-materialize $(if $(LIMIT),LIMIT=$(LIMIT),)
	$(MAKE) skill-strip-faults $(if $(LIMIT),LIMIT=$(LIMIT),)

skill-generate: ## run Copilot SDK concurrently in services_skill (MODEL/WORKERS/RUN_ID optional)
	$${PYTHON:-python3} tools/run_services_skill_sdk_generation.py $(if $(SVC),$(SVC),) $(if $(LIMIT),--limit $(LIMIT),) $(if $(MODEL),--model $(MODEL),) $(if $(WORKERS),--workers $(WORKERS),) $(if $(RUN_ID),--run-id $(RUN_ID),) $(if $(CLEAN_SRC),--clean-src,)

skill-prepare-workspace: ## create isolated SDK workspaces with only public prompt/contract (LIMIT=N optional)
	python3 tools/skill_experiment.py prepare-workspace --prompt-variant $(PROMPT_VARIANT) $(if $(LIMIT),--limit $(LIMIT),) $(if $(SVC),--services $(SVC),)

skill-generate-isolated: ## run Copilot SDK in isolated workspaces (LIMIT=N or SVC=name optional)
	$${PYTHON:-python3} tools/run_isolated_sdk_generation.py $(if $(SVC),$(SVC),) $(if $(LIMIT),--limit $(LIMIT),) $(if $(WORKERS),--workers $(WORKERS),)

skill-import-generated: ## copy isolated workspace src/ back into services_skill (LIMIT=N optional)
	python3 tools/skill_experiment.py import-generated $(if $(LIMIT),--limit $(LIMIT),)

list-skill: ## list generated skill service skeletons
	@for s in $(SKILL_SERVICES); do echo "  $$s"; done

compare-skill: ## compare latest baseline runs with matching skill runs
	python3 tools/compare_skill_results.py $(if $(LIMIT),--limit $(LIMIT),)

stop-skill-runs: ## stop active/interrupted parallel services_skill capture workers
	bash tools/stop_skill_runs.sh

# Per-service delegation. All wrappers pass through to services/<SVC>/run.sh.
build: _check_svc
	bash services/$(SVC)/run.sh build

deploy: _check_svc
	bash services/$(SVC)/run.sh deploy

wait: _check_svc
	bash services/$(SVC)/run.sh wait

smoke: _check_svc
	bash services/$(SVC)/run.sh smoke

inject: _check_svc _check_fault
	bash services/$(SVC)/run.sh inject $(FAULT)

judge: _check_svc
	bash services/$(SVC)/run.sh judge

cleanup: _check_svc
	bash services/$(SVC)/run.sh cleanup

capture: _check_svc ## build + deploy + smoke + run every applicable fault; no judge/scoring
	bash services/$(SVC)/run.sh capture

demo: _check_svc ## build + deploy + smoke + run every applicable fault + judge
	bash services/$(SVC)/run.sh demo

build-skill: _check_skill_svc
	bash services_skill/$(SVC)/run.sh build

deploy-skill: _check_skill_svc
	bash services_skill/$(SVC)/run.sh deploy

wait-skill: _check_skill_svc
	bash services_skill/$(SVC)/run.sh wait

smoke-skill: _check_skill_svc
	bash services_skill/$(SVC)/run.sh smoke

inject-skill: _check_skill_svc _check_skill_fault
	bash services_skill/$(SVC)/run.sh inject $(FAULT)

judge-skill: _check_skill_svc
	bash services_skill/$(SVC)/run.sh judge

cleanup-skill: _check_skill_svc
	bash services_skill/$(SVC)/run.sh cleanup

capture-skill: _check_skill_svc ## build + deploy + faults for a services_skill entry; no judge/scoring
	bash services_skill/$(SVC)/run.sh capture

demo-skill: _check_skill_svc ## build + deploy + faults + judge for a services_skill entry
	bash services_skill/$(SVC)/run.sh demo

all: ## run `make demo` for every service in sequence (slow; includes judge)
	@for s in $(SERVICES); do \
		echo "=== $$s ==="; \
		$(MAKE) demo SVC=$$s || echo "  (failed, continuing)"; \
		$(MAKE) cleanup SVC=$$s || true; \
	done

all-skill: ## run `make demo-skill` for every services_skill entry in sequence (slow; includes judge)
	@for s in $(SKILL_SERVICES); do \
		echo "=== $$s ==="; \
		$(MAKE) demo-skill SVC=$$s || echo "  (failed, continuing)"; \
		$(MAKE) cleanup-skill SVC=$$s || true; \
	done

_check_svc:
	@if [[ -z "$(SVC)" ]]; then \
		echo "error: SVC=<id> required (e.g. SVC=01-catalog-api)"; \
		exit 2; \
	fi
	@if [[ ! -d "services/$(SVC)" ]]; then \
		echo "error: no such service services/$(SVC)"; \
		echo "available:"; for s in $(SERVICES); do echo "  $$s"; done; \
		exit 2; \
	fi

_check_fault:
	@if [[ -z "$(FAULT)" ]]; then \
		echo "error: FAULT=<id> required (e.g. FAULT=F01-pod-kill)"; \
		ls services/$(SVC)/faults/ 2>/dev/null | sed 's/\.yaml//; s/^/  /'; \
		exit 2; \
	fi

_check_skill_svc:
	@if [[ -z "$(SVC)" ]]; then \
		echo "error: SVC=<id>-skill required (e.g. SVC=01-catalog-api-skill)"; \
		exit 2; \
	fi
	@if [[ ! -d "services_skill/$(SVC)" ]]; then \
		echo "error: no such skill service services_skill/$(SVC)"; \
		echo "available:"; for s in $(SKILL_SERVICES); do echo "  $$s"; done; \
		exit 2; \
	fi

_check_skill_fault:
	@if [[ -z "$(FAULT)" ]]; then \
		echo "error: FAULT=<id> required (e.g. FAULT=F01-pod-kill)"; \
		ls services_skill/$(SVC)/faults/ 2>/dev/null | sed 's/\.yaml//; s/^/  /'; \
		exit 2; \
	fi
