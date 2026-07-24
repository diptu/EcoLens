# ─────────────────────────────────────────────────────────────────────────────
# ecoLens — Production-grade Makefile
# ─────────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

# ── Vars ────────────────────────────────────────────────────────────────────
UV       ?= uv
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
	$(UV) sync --all-packages --all-groups
	$(UV) run pre-commit install
	@$(MAKE) check-env

.PHONY: clean
clean: ## Hard reset of local environment.
	@read -p "Are you sure? This deletes .venv and build artifacts. [y/N] " confirm && [ "$$confirm" = "y" ]
	rm -rf .venv dist build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +

# ── Infrastructure ──────────────────────────────────────────────────────────
.PHONY: up
up: check-env ## Spin up services using profiles.
	$(COMPOSE) -f $(DC_FILE) up -d --remove-orphans

.PHONY: down
down: ## Stop all services.
	$(COMPOSE) -f $(DC_FILE) down

# ── Quality Assurance ───────────────────────────────────────────────────────
.PHONY: lint
lint: ## Run comprehensive suite (ruff + mypy + security).
	# Lint everything for style
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	# Run type-checking per service (mypy errors out on a dir with no
	# .py files yet, e.g. forecast-api/src before it's scaffolded)
	@targets=""; \
	for dir in services/forecast-api/src services/data-pipeline/src; do \
		if find "$$dir" -name '*.py' -print -quit | grep -q .; then \
			targets="$$targets $$dir"; \
		else \
			echo "Skipping mypy for $$dir: no .py files yet"; \
		fi; \
	done; \
	$(UV) run mypy $$targets
	# Run security checks
	$(UV) run bandit -r services/forecast-api/src services/data-pipeline/src

.PHONY: lint-fix
lint-fix: ## Run fix (ruff).
	# Fix Lint
	$(UV) run ruff check --fix .
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

.PHONY: test
test: ## Run test suite with security checks.
	$(UV) run pytest -m "not e2e" \
		--cov=services/data-pipeline/src \
		--cov=services/forecast-api/src \
		--cov-fail-under=90
	$(UV) run pip-audit

# ── TODOs ───────────────────────────────────────────────────────────────────
.PHONY: todos
todos: list-todos todos-structure audit ## Full TODO report: list tagged items, sync structure checklist, audit orphans.

.PHONY: list-todos
list-todos: ## Print all tagged TODOs (e.g. [ECO-101], [ING-0301]) from every TODO.md.
	@for f in TODO.md services/*/TODO.md; do \
		[ -f "$$f" ] || continue; \
		echo "── $$f ──"; \
		grep -E '\[[A-Z]+-[A-Z0-9-]+\]' "$$f" || echo "  (no tagged TODOs)"; \
		echo; \
	done

.PHONY: todos-structure
todos-structure: ## Sync each service's TODO.md "Structure" checklist with its src/ tree on disk.
	@bash services/scripts/update_structure_todos.sh

.PHONY: todo
todo: ## Add a new TODO. Usage: make todo DESC="..." [SVC=forecast-api|data-pipeline|dashboard]
	@bash scripts/add_todo.sh "$(DESC)" "$(SVC)"

.PHONY: audit
audit: ## Warn about TODO tags present in code but missing from TODO.md.
	@bash scripts/audit_todos.sh

# ── Services ────────────────────────────────────────────────────────────────
.PHONY: api
api: ## Run forecast-api locally (dev: single process, auto-reload).
	cd services/forecast-api && $(UV) run --package forecast-api uvicorn ecolens_forecast_api.main:app --reload --port 8003

.PHONY: api-prod
api-prod: ## Run forecast-api under Gunicorn + UvicornWorker (production process model, ECO-F01).
	cd services/forecast-api && $(UV) run --package forecast-api gunicorn -c gunicorn_conf.py --chdir src ecolens_forecast_api.main:app

.PHONY: pipeline
pipeline: ## Run data-pipeline locally.
	cd services/data-pipeline && $(UV) run --package data-pipeline uvicorn ecolens.api.app:app --reload --port 8001

.PHONY: ingest-openelectricity
ingest-openelectricity: ## Manually trigger one OpenElectricity (NEM/WEM) fetch -> validate -> Mongo upsert.
	cd services/data-pipeline && $(UV) run --active python scripts/trigger_ingest_openelectricity.py

.PHONY: ingest-aemo-nem
ingest-aemo-nem: ## Manually trigger one AEMO NEM dispatch fetch -> Mongo upsert. Usage: make ingest-aemo-nem [DATE=2026-07-19] (default: yesterday, AEST).
	cd services/data-pipeline && $(UV) run --active python scripts/trigger_ingest_aemo_nem.py $(if $(DATE),--date $(DATE),)

.PHONY: ingest-aemo-wem
ingest-aemo-wem: ## Manually trigger one AEMO WEM dispatch fetch -> Mongo upsert. Usage: make ingest-aemo-wem [DATE=2026-07-18] (default: yesterday, AWST).
	cd services/data-pipeline && $(UV) run --active python scripts/trigger_ingest_aemo_wem.py $(if $(DATE),--date $(DATE),)

.PHONY: ingest-bom
ingest-bom: ## Manually trigger BoM weather observation fetch(es) -> validate -> Mongo upsert. Usage: make ingest-bom [DATE=2026-07-01] | [START_DATE=2026-06-01 END_DATE=2026-07-01] (default: last 1 hour).
	cd services/data-pipeline && $(UV) run --active python scripts/trigger_ingest_bom.py $(if $(DATE),--date $(DATE),) $(if $(START_DATE),--start-date $(START_DATE),) $(if $(END_DATE),--end-date $(END_DATE),)

.PHONY: ingest-holidays
ingest-holidays: ## Manually trigger public-holidays fetch(es) -> validate -> Mongo upsert. Usage: make ingest-holidays [YEAR=2027] | [START_YEAR=2015 END_YEAR=2027] (default: current year).
	cd services/data-pipeline && $(UV) run --active python scripts/trigger_ingest_holidays.py $(if $(YEAR),--year $(YEAR),) $(if $(START_YEAR),--start-year $(START_YEAR),) $(if $(END_YEAR),--end-year $(END_YEAR),)

.PHONY: ingest-all
ingest-all: ingest-openelectricity ingest-aemo-nem ingest-aemo-wem ingest-bom ingest-holidays ## Manually trigger all five ingest sources in sequence.

.PHONY: backfill-bom-historical
backfill-bom-historical: ## Backfill historical BoM weather via Open-Meteo (ERA5) -> validate -> Mongo upsert. Usage: make backfill-bom-historical [YEARS=2] | [START_DATE=2023-01-01 END_DATE=2023-12-31] (default: 3 years).
	cd services/data-pipeline && $(UV) run --active python scripts/backfill_bom_historical.py $(if $(YEARS),--years $(YEARS),) $(if $(START_DATE),--start-date $(START_DATE),) $(if $(END_DATE),--end-date $(END_DATE),)

.PHONY: backfill-aemo
backfill-aemo: ## Backfill AEMO NEM/WEM over a date range, day by day. Usage: make backfill-aemo START=2026-07-01 [END=2026-07-19] [SOURCE=nem|wem|both].
	@if [ -z "$(START)" ]; then echo "Usage: make backfill-aemo START=2026-07-01 [END=2026-07-19] [SOURCE=nem|wem|both]"; exit 1; fi
	cd services/data-pipeline && $(UV) run --active python ../scripts/backfill_aemo.py --start $(START) $(if $(END),--end $(END),) $(if $(SOURCE),--source $(SOURCE),)

.PHONY: backfill-aemo-nem
backfill-aemo-nem: ## Backfill AEMO NEM over a date range, day by day. Usage: make backfill-aemo-nem START=2026-07-01 [END=2026-07-19].
	@if [ -z "$(START)" ]; then echo "Usage: make backfill-aemo-nem START=2026-07-01 [END=2026-07-19]"; exit 1; fi
	cd services/data-pipeline && $(UV) run --active python ../scripts/backfill_aemo.py --start $(START) $(if $(END),--end $(END),) --source nem

.PHONY: backfill-aemo-wem
backfill-aemo-wem: ## Backfill AEMO WEM over a date range, day by day. Usage: make backfill-aemo-wem START=2026-07-01 [END=2026-07-19].
	@if [ -z "$(START)" ]; then echo "Usage: make backfill-aemo-wem START=2026-07-01 [END=2026-07-19]"; exit 1; fi
	cd services/data-pipeline && $(UV) run --active python ../scripts/backfill_aemo.py --start $(START) $(if $(END),--end $(END),) --source wem

# ── Forecasting Model (train/tune/evaluate/promote in data-pipeline; ──────
# ── forecast-api never trains, it only loads+serves whatever is aliased ───
# ── "production" in the MLflow Registry -- see services/forecast-api/ ─────
# ── strategy.md §2 and root TODO.md ECO-108..119.) ─────────────────────────
.PHONY: model-train
model-train: ## Full train -> evaluate -> promote-if-better cycle (weekly cron). Registers a new version and promotes it iff it beats the current "production" alias. Trains on a live Colab T4 GPU bridge if NTFY_TOPIC is set (see scripts/colab_server.py) and a kernel is published, else local CPU/CUDA. Usage: make model-train [NO_COLAB=1].
	cd services/data-pipeline && $(UV) run --active python -m ecolens.forecasting.cli train $(if $(NO_COLAB),--no-colab,)

.PHONY: model-tune
model-tune: ## Optuna hyperparameter search (occasional, manual). Usage: make model-tune [N_TRIALS=20].
	cd services/data-pipeline && $(UV) run --active python -m ecolens.forecasting.cli tune $(if $(N_TRIALS),--n-trials $(N_TRIALS),)

.PHONY: model-evaluate
model-evaluate: ## Re-evaluate the current "production"-aliased model against fresh data (MAPE/RMSE/coverage), no retrain.
	cd services/data-pipeline && $(UV) run --active python -m ecolens.forecasting.cli evaluate

.PHONY: model-status
model-status: ## Print the current production model's version/last-trained/last-eval snapshot (health.get_health_snapshot).
	cd services/data-pipeline && $(UV) run --active python -m ecolens.forecasting.cli status

.PHONY: model-online-finetune
model-online-finetune: ## Lightweight fine-tune of the current production model on the newest window (more frequent cron than model-train; still gated by promote_if_better).
	cd services/data-pipeline && $(UV) run --active python -m ecolens.forecasting.cli online-finetune

.PHONY: model-benchmark
model-benchmark: ## Benchmark forecast-api's CPU inference optimization (ECO-P03: quantized vs fp32 latency/RSS). Usage: make model-benchmark [ITERATIONS=200] [HIDDEN_SIZE=128] [NUM_LAYERS=2].
	cd services/forecast-api && $(UV) run --active python scripts/benchmark_inference.py $(if $(ITERATIONS),--iterations $(ITERATIONS),) $(if $(HIDDEN_SIZE),--hidden-size $(HIDDEN_SIZE),) $(if $(NUM_LAYERS),--num-layers $(NUM_LAYERS),)

.PHONY: plot-data-frequency
plot-data-frequency: ## Bar chart of ml_features_demand_v1 row count per day over a date range. Usage: make plot-data-frequency START_DATE=2026-01-01 END_DATE=2026-07-01 [REGION=NSW1] [OUTPUT=path.png].
	@if [ -z "$(START_DATE)" ] || [ -z "$(END_DATE)" ]; then echo "Usage: make plot-data-frequency START_DATE=2026-01-01 END_DATE=2026-07-01 [REGION=NSW1] [OUTPUT=path.png]"; exit 1; fi
	cd services/data-pipeline && $(UV) run --active python scripts/plot_data_frequency.py --start-date $(START_DATE) --end-date $(END_DATE) $(if $(REGION),--region $(REGION),) $(if $(OUTPUT),--output $(OUTPUT),)

.PHONY: validate-features
validate-features: ## Empirically validates candidate model features against every raw/staging ingested column (not just ml_features_demand_v1) -- missingness, variance, correlation/mutual-info/RandomForest importance vs. the horizon-ahead target -- over a date range. Defaults to the last 6 months if START_DATE/END_DATE aren't given. Usage: make validate-features [START_DATE=2026-01-01] [END_DATE=2026-07-01] [REGION=NSW1].
	@end="$(END_DATE)"; start="$(START_DATE)"; \
	if [ -z "$$end" ]; then end=$$(date +%Y-%m-%d); fi; \
	if [ -z "$$start" ]; then start=$$(date -v-6m +%Y-%m-%d 2>/dev/null || date -d "6 months ago" +%Y-%m-%d); fi; \
	echo "Validating features from $$start to $$end"; \
	cd services/data-pipeline && $(UV) run --active python scripts/validate_feature_columns.py --start-date $$start --end-date $$end $(if $(REGION),--region $(REGION),)

.PHONY: mlflow-ui
mlflow-ui: ## Browse MLflow experiment tracking (runs/params/metrics/registered models) for the local SQLite store. Usage: make mlflow-ui [PORT=5001].
	@port="$(if $(PORT),$(PORT),5001)"; \
	uri="$$(cd services/data-pipeline && $(UV) run --active python -c 'from ecolens.config import get_settings; print(get_settings().mlflow_tracking_uri)')"; \
	echo "Tracking store: $$uri"; \
	echo "Open http://127.0.0.1:$$port in your browser -- use the literal '127.0.0.1', not 'localhost'"; \
	echo "(mlflow's own localhost-only security middleware rejects the IPv6 '::1' most browsers/OSes resolve 'localhost' to first)."; \
	echo; \
	echo "Runs via 'uvx --from mlflow' -- an isolated environment separate from this"; \
	echo "workspace's own venv, since the full mlflow package (needed for its bundled"; \
	echo "web UI; mlflow-skinny ships no frontend assets at all) forces a pandas"; \
	echo "downgrade (3.x -> 2.x) that would conflict with this project's pandas>=3.0.3."; \
	echo "First run downloads/caches mlflow + its full dependency set (~10s-1min); reused after."; \
	uvx --from mlflow mlflow ui --backend-store-uri "$$uri" --port "$$port"

# ── Warehouse (MongoDB raw -> PostgreSQL raw.* -> dbt) ─────────────────────
# DBT_TARGET/DBT_SELECT are for the direct `dbt-*` passthrough targets below
# (ad-hoc project work); the `warehouse*` targets go through the Python
# runner instead, which defaults its own dbt --target to "prod" (see
# WarehouseRunnerSettings) -- the two defaults differ on purpose.
DATA_PIPELINE_DIR := $(CURDIR)/services/data-pipeline
DBT_PROJECT_DIR   := services/data-pipeline/src/ecolens/warehouse/dbt_project
DBT_TARGET        ?= dev
DBT_RUN           := cd $(DBT_PROJECT_DIR) && $(UV) run --active --project $(DATA_PIPELINE_DIR) dbt

.PHONY: warehouse
warehouse: ## Run the warehouse pipeline: raw sync + dbt build + quality + aggregates. Usage: make warehouse [MODE=incremental|full|validate] [SELECT="tag:marts"] [EXCLUDE="tag:dev"].
	cd services/data-pipeline && $(UV) run --active python -m ecolens.warehouse.runner.runner \
		$(if $(filter full,$(MODE)),--full,$(if $(filter validate,$(MODE)),--validate-only,--incremental)) \
		$(if $(SELECT),--select $(SELECT),) \
		$(if $(EXCLUDE),--exclude $(EXCLUDE),)

.PHONY: warehouse-full
warehouse-full: ## Full warehouse refresh (weekly cron): resyncs all raw history + dbt --full-refresh.
	cd services/data-pipeline && $(UV) run --active python -m ecolens.warehouse.runner.runner --full

.PHONY: warehouse-validate
warehouse-validate: ## Check source freshness + warehouse state without running dbt.
	cd services/data-pipeline && $(UV) run --active python -m ecolens.warehouse.runner.runner --validate-only

.PHONY: warehouse-bootstrap
warehouse-bootstrap: ## Bootstrap raw.* Postgres tables (idempotent create_raw_schema macro) without running the full pipeline. Usage: make warehouse-bootstrap [DBT_TARGET=dev|staging|prod].
	$(DBT_RUN) run-operation create_raw_schema --profiles-dir . --target $(DBT_TARGET)

.PHONY: warehouse-logs
warehouse-logs: ## Tail the warehouse runner's JSONL run log (data/log/warehouse-runs.jsonl).
	@tail -f services/data-pipeline/data/log/warehouse-runs.jsonl

.PHONY: sync-raw
sync-raw: ## Manually trigger MongoDB -> PostgreSQL raw.* sync only (no dbt). Usage: make sync-raw [FULL=1] [LOOKBACK_DAYS=10].
	cd services/data-pipeline && $(UV) run --active python scripts/sync_raw.py $(if $(FULL),--full,) $(if $(LOOKBACK_DAYS),--lookback-days $(LOOKBACK_DAYS),)

# ── dbt direct access (warehouse project) ──────────────────────────────────
# For ad-hoc project work (compiling/testing one model, checking docs)
# without going through the Python runner's freshness/quality/aggregate
# stages. Usage: make dbt-build [DBT_SELECT="tag:marts"] [DBT_TARGET=prod].
.PHONY: dbt-build
dbt-build: ## Run `dbt build` directly against the warehouse project.
	$(DBT_RUN) build --profiles-dir . --target $(DBT_TARGET) $(if $(DBT_SELECT),--select $(DBT_SELECT),) $(if $(FULL),--full-refresh,)

.PHONY: dbt-run
dbt-run: ## Run `dbt run` (models only, no tests) directly against the warehouse project.
	$(DBT_RUN) run --profiles-dir . --target $(DBT_TARGET) $(if $(DBT_SELECT),--select $(DBT_SELECT),) $(if $(FULL),--full-refresh,)

.PHONY: dbt-test
dbt-test: ## Run `dbt test` directly against the warehouse project.
	$(DBT_RUN) test --profiles-dir . --target $(DBT_TARGET) $(if $(DBT_SELECT),--select $(DBT_SELECT),)

.PHONY: dbt-seed
dbt-seed: ## Run `dbt seed` (e.g. the region_reference dimension) directly against the warehouse project.
	$(DBT_RUN) seed --profiles-dir . --target $(DBT_TARGET)

.PHONY: dbt-docs
dbt-docs: ## Generate + serve dbt docs for the warehouse project (http://localhost:8080).
	$(DBT_RUN) docs generate --profiles-dir . --target $(DBT_TARGET)
	$(DBT_RUN) docs serve --profiles-dir . --target $(DBT_TARGET)

.PHONY: dbt-clean
dbt-clean: ## Remove the warehouse dbt project's target/ and logs/ (compiled SQL + run artifacts).
	rm -rf $(DBT_PROJECT_DIR)/target $(DBT_PROJECT_DIR)/logs

.PHONY: web
web: ## Run Next.js (requires pnpm).
	cd services/dashboard && pnpm dev

# ── Release ─────────────────────────────────────────────────────────────────
.PHONY: deploy
deploy: ## Deploy with target validation.
	@if [ -z "$(DEPLOY_TARGET)" ]; then echo "Usage: make deploy DEPLOY_TARGET=prod"; exit 1; fi
	@echo "Deploying to $(DEPLOY_TARGET)..."
	bash scripts/deploy.sh $(DEPLOY_TARGET)
