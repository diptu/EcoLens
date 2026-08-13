# ─────────────────────────────────────────────────────────────────────────────
# ecoLens — Production-grade Makefile
# ─────────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

# ── Vars ────────────────────────────────────────────────────────────────────
UV       ?= uv
DOCKER   ?= docker
COMPOSE  ?= docker compose
DC_FILE  ?= docker-compose.yml
ENV_FILE ?= .env

# Include environment variables
ifneq (,$(wildcard $(ENV_FILE)))
    include $(ENV_FILE)
    export
endif
# ────────────────────────────────────────────────────────────────────────────
# Help
# ────────────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help message.
	@printf "\033[1m%-20s %s\033[0m\n" "TARGET" "DESCRIPTION"
	@printf "%-20s %s\n" "------" "-----------"
	@cat $(firstword $(MAKEFILE_LIST)) | \
		grep -E '^[a-zA-Z_-]+:.*?## .*$$' | \
		sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

check-env: ## Verify .env file exists.
	@if [ ! -f $(ENV_FILE) ]; then echo "Error: $(ENV_FILE) missing." && exit 1; fi

# ── Bootstrap & Maintenance ─────────────────────────────────────────────────
.PHONY: bootstrap
bootstrap: ## Full environment sync + pre-commit.
	$(UV) sync --all-extras --all-groups
	# forecast-api/ingestion are their own independent uv projects (own
	# venv/lockfile, not workspace members) -- synced separately.
	$(UV) sync --directory services/forecast-api
	$(UV) sync --directory services/ingestion
	$(UV) run pre-commit install
	@$(MAKE) check-env

.PHONY: clean
clean: ## Hard reset of local environment.
	@read -p "Are you sure? This deletes .venv and build artifacts. [y/N] " confirm && [ "$$confirm" = "y" ]
	rm -rf .venv dist build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	rm -rf services/forecast-api/.venv services/forecast-api/dist services/forecast-api/build \
		services/forecast-api/.pytest_cache services/forecast-api/.mypy_cache \
		services/forecast-api/.ruff_cache services/forecast-api/.coverage services/forecast-api/htmlcov
	rm -rf services/ingestion/.venv services/ingestion/dist services/ingestion/build \
		services/ingestion/.pytest_cache services/ingestion/.mypy_cache \
		services/ingestion/.ruff_cache services/ingestion/.coverage services/ingestion/htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +

# ── Infrastructure ──────────────────────────────────────────────────────────
.PHONY: up
up: check-env ## Spin up services using profiles.
	$(COMPOSE) -f $(DC_FILE) up -d --remove-orphans

.PHONY: down
down: ## Stop all services.
	$(COMPOSE) -f $(DC_FILE) down

# ── Docker Images ───────────────────────────────────────────────────────────
# One target per real infra/docker/*.Dockerfile (`docker.yml`'s own build
# matrix, mirrored locally, plus `ingestion`/`mlflow` which that workflow
# doesn't build but docker-compose.yml does). `worker`/`web` are deliberately
# excluded: docker-compose.yml references infra/docker/{worker,web}.Dockerfile
# but neither file exists yet (`docker.yml`'s own "web has no Dockerfile yet"
# note -- same gap, not something this target papers over).
IMAGE_TAG        ?= local
DOCKER_SERVICES  := data-pipeline forecast-api warehouse ingestion mlflow

.PHONY: docker-build
docker-build: ## Build Docker image(s) from infra/docker/*.Dockerfile. Pass SERVICE=forecast-api to build just one; IMAGE_TAG=local overrides the tag.
	@for svc in $(if $(SERVICE),$(SERVICE),$(DOCKER_SERVICES)); do \
		if [ ! -f infra/docker/$$svc.Dockerfile ]; then \
			echo "Unknown SERVICE '$$svc' -- no infra/docker/$$svc.Dockerfile (have: $(DOCKER_SERVICES))"; exit 1; \
		fi; \
		echo "── docker build $$svc:$(IMAGE_TAG) ──"; \
		$(DOCKER) build -f infra/docker/$$svc.Dockerfile -t ecolens/$$svc:$(IMAGE_TAG) . || exit 1; \
	done

# ── Quality Assurance ───────────────────────────────────────────────────────
.PHONY: lint
lint: ## Run comprehensive suite (ruff + mypy + security).
	# Lint everything for style. forecast-api/ingestion are their own
	# independent uv projects now (own venv/lockfile, not workspace
	# members -- both packages are named `app`, same as data-pipeline's,
	# so sharing one workspace venv would collide them), so each is
	# linted via its own venv rather than the root `$(UV) run`.
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run --directory services/forecast-api ruff check .
	$(UV) run --directory services/ingestion ruff check .
	$(UV) run --directory services/ingestion ruff format --check .
	# Run type-checking per service
	$(UV) run mypy services/data-pipeline/app
	$(UV) run --directory services/forecast-api mypy app
	$(UV) run --directory services/ingestion mypy app
	# Run security checks
	$(UV) run bandit -r services/data-pipeline/app services/forecast-api/app services/ingestion/app

.PHONY: lint-fix
lint-fix: ## Run fix (ruff).
	# Fix Lint
	$(UV) run ruff check --fix .
	$(UV) run ruff format .
	$(UV) run ruff check --fix .


.PHONY: test
test: check-env ## Run test suite with security checks.
	# data-pipeline is the one remaining root-uv-workspace service. Not a
	# bare `pytest -m "not e2e"` -- that would also collect
	# services/iam/tests (a separate, non-workspace service whose own
	# pytest-asyncio dev dependency isn't installed in this venv, so its
	# `@pytest.mark.asyncio` tests fail with "async def functions are not
	# natively supported" here) and services/dashboard, if either grows a
	# test suite later.
	$(UV) run pytest services/data-pipeline -m "not e2e" \
		--cov=services/data-pipeline/app \
		--cov-fail-under=90
	# forecast-api/ingestion are their own independent uv projects (own
	# venv/lockfile), so each is tested via its own venv rather than the
	# root `$(UV) run`.
	$(UV) run --directory services/forecast-api pytest -m "not e2e" \
		--cov=app \
		--cov-fail-under=90
	$(UV) run --directory services/ingestion pytest -m "not e2e" \
		--cov=app \
		--cov-fail-under=90
	# PYSEC-2026-3552 (cryptography <50) is ignored deliberately, not
	# silently: `mlflow` (every released version through 3.15.0, the
	# latest) pins `cryptography<50`, so `cryptography>=50.0.0` is
	# currently unsatisfiable in either project's dependency graph
	# without dropping to an mlflow pre-release (confirmed via `uv lock
	# --upgrade-package "cryptography>=50.0.0"`'s resolver conflict, not
	# assumed) -- re-check this ignore next time mlflow's own
	# `cryptography` ceiling moves.
	$(UV) run pip-audit --ignore-vuln PYSEC-2026-3552
	$(UV) run --directory services/forecast-api pip-audit --ignore-vuln PYSEC-2026-3552
	# ingestion has no mlflow/cryptography dependency chain at all (a
	# deliberately much smaller dependency set, `services/ingestion/
	# TODO.md`'s Phase 0 scoping) -- no ignore needed unless/until a real
	# vulnerability shows up here.
	$(UV) run --directory services/ingestion pip-audit

# ── Services ────────────────────────────────────────────────────────────────
.PHONY: api
api: ## Run forecast-api locally.
	$(UV) run --directory services/forecast-api uvicorn app.main:app --reload --port 8000

.PHONY: pipeline
pipeline: ## Run data-pipeline locally.
	$(UV) run --package data-pipeline uvicorn app.main:app --reload --port 8001

.PHONY: web
web: ## Run Next.js (requires pnpm).
	cd services/dashboard && pnpm dev

# ── dbt ─────────────────────────────────────────────────────────────────────
.PHONY: dbt-build
dbt-build: ## Run `dbt build` against the warehouse (services/data-pipeline/dbt/ecolens). Pass TARGET=dev to override.
	$(UV) run --package data-pipeline ecolens-pipeline dbt build $(if $(TARGET),--target $(TARGET))

# ── ML ──────────────────────────────────────────────────────────────────────
# `todo-model-training.md`'s "Training all three models" plan: one joint
# LSTM/TFT model conditioned on all 6 real regions in a single run, not 6
# separate single-region models (`train_and_register`'s `regions` arg
# already supports this -- confirmed directly against its own code).
# `--region` is `multiple=True` (cli.py) -- passing it once per region is
# the real CLI contract, not a comma-joined list. UPDATE 2026-08-05: the
# root region-join bug is fixed (`ingest_openelectricity.py` now queries
# OE per-region for real) and a real 21-day historical backfill landed
# (2026-07-15 -> 2026-08-04, 34,548 real rows, all 6 regions) -- 27,328
# real usable feature rows exist now. `--since` (also new) is required
# to actually use them: `split_by_time`'s 70/15/15 split is chronological
# over the *entire* AEMO history (~370 days), so without it, real data
# confined to this recent 21-day window mostly lands in the `test` split
# and starves train/val/calibration (confirmed live: got 20/5/0 rows
# without --since). `SINCE` below defaults to the real backfill's start
# date -- override if a different/wider backfill exists later. See
# `todo-model-training.md`'s "Blocker" section for the full writeup.
ALL_TRAIN_REGIONS := NSW1 QLD1 VIC1 SA1 TAS1 WEM
SINCE ?= 2026-07-15

.PHONY: train
train: ## Train the demand-forecast LSTM jointly across all 6 real regions and log/register it in MLflow. Pass REGION=NSW1 to train a single region, SINCE=YYYY-MM-DD to override the real-data window (see todo-model-training.md).
	$(UV) run --package data-pipeline ecolens-pipeline train --since $(SINCE) $(if $(REGION),--region $(REGION),$(foreach r,$(ALL_TRAIN_REGIONS),--region $(r)))

.PHONY: train-tft
train-tft: ## Train the demand-forecast TFT jointly across all 6 real regions and log/register it under lstm_demand_tft in MLflow. Pass REGION=NSW1 to train a single region, SINCE=YYYY-MM-DD to override the real-data window (see todo-model-training.md).
	$(UV) run --package data-pipeline ecolens-pipeline train-tft --since $(SINCE) $(if $(REGION),--region $(REGION),$(foreach r,$(ALL_TRAIN_REGIONS),--region $(r)))

.PHONY: tune
tune: ## Small grid search over hidden_size/lr, each trial logged to MLflow. Pass REGION=NSW1 to override.
	$(UV) run --package data-pipeline ecolens-pipeline tune $(if $(REGION),--region $(REGION))

.PHONY: tune-optuna
tune-optuna: ## Real Optuna TPE search + final full retrain/register. Pass REGION=NSW1, N_TRIALS=20, DATA_SOURCE=ml_features_v1, TRAIN_FRAC=0.6, VAL_FRAC=0.2 to override.
	$(UV) run --package data-pipeline ecolens-pipeline tune-optuna \
		$(if $(REGION),--region $(REGION)) \
		$(if $(N_TRIALS),--n-trials $(N_TRIALS)) \
		$(if $(DATA_SOURCE),--data-source $(DATA_SOURCE)) \
		$(if $(TRAIN_FRAC),--train-frac $(TRAIN_FRAC)) \
		$(if $(VAL_FRAC),--val-frac $(VAL_FRAC))

.PHONY: evaluate
evaluate: ## Walk-forward backtest a registered model version vs. the seasonal-naive baseline. Usage: make evaluate VERSION=1 [MODEL_NAME=lstm_demand] [REGION=NSW1].
	@if [ -z "$(VERSION)" ]; then echo "Usage: make evaluate VERSION=1 [MODEL_NAME=lstm_demand] [REGION=NSW1]"; exit 1; fi
	$(UV) run --package data-pipeline ecolens-pipeline evaluate --version $(VERSION) $(if $(MODEL_NAME),--model-name $(MODEL_NAME)) $(if $(REGION),--region $(REGION))

.PHONY: evaluate-tft
evaluate-tft: ## Walk-forward backtest a registered TFT version vs. the seasonal-naive baseline. Usage: make evaluate-tft VERSION=1 [REGION=NSW1].
	@if [ -z "$(VERSION)" ]; then echo "Usage: make evaluate-tft VERSION=1 [REGION=NSW1]"; exit 1; fi
	$(UV) run --package data-pipeline ecolens-pipeline evaluate-tft --version $(VERSION) $(if $(REGION),--region $(REGION))

.PHONY: prune
prune: ## Structured pruning + fine-tune recovery for a registered LSTM version. Usage: make prune VERSION=1 [KEEP_FRACTION=0.5] [REGION=NSW1].
	@if [ -z "$(VERSION)" ]; then echo "Usage: make prune VERSION=1 [KEEP_FRACTION=0.5] [REGION=NSW1]"; exit 1; fi
	$(UV) run --package data-pipeline ecolens-pipeline prune --version $(VERSION) $(if $(KEEP_FRACTION),--keep-fraction $(KEEP_FRACTION)) $(if $(REGION),--region $(REGION))

.PHONY: evaluate-timesfm
evaluate-timesfm: ## Walk-forward backtest TimesFM (zero-shot) vs. the seasonal-naive baseline. Pass REGION=WEM to override.
	$(UV) run --package data-pipeline ecolens-pipeline evaluate-timesfm $(if $(REGION),--region $(REGION))

# ── Release ─────────────────────────────────────────────────────────────────
.PHONY: deploy
deploy: ## Deploy with target validation.
	@if [ -z "$(DEPLOY_TARGET)" ]; then echo "Usage: make deploy DEPLOY_TARGET=prod"; exit 1; fi
	@echo "Deploying to $(DEPLOY_TARGET)..."
	bash scripts/deploy.sh $(DEPLOY_TARGET)

.PHONY: audit
audit: ## Audit all services for undocumented TODOs
	@bash scripts/audit_todos.sh

.PHONY: list-todos
list-todos: ## Print all TODOs from all services
	@for f in TODO.md services/*/TODO.md; do \
		[ -f "$$f" ] || continue; \
		echo "── $$f ──"; \
		grep -E '\[ECO-[A-Z0-9-]+\]' "$$f" || echo "  (no tagged TODOs)"; \
		echo; \
	done