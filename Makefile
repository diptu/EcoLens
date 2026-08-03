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
	$(UV) sync --all-extras --all-groups
	# forecast-api is its own independent uv project (own venv/lockfile,
	# not a workspace member) -- synced separately.
	$(UV) sync --directory services/forecast-api
	$(UV) run pre-commit install
	@$(MAKE) check-env

.PHONY: clean
clean: ## Hard reset of local environment.
	@read -p "Are you sure? This deletes .venv and build artifacts. [y/N] " confirm && [ "$$confirm" = "y" ]
	rm -rf .venv dist build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	rm -rf services/forecast-api/.venv services/forecast-api/dist services/forecast-api/build \
		services/forecast-api/.pytest_cache services/forecast-api/.mypy_cache \
		services/forecast-api/.ruff_cache services/forecast-api/.coverage services/forecast-api/htmlcov
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
	# Lint everything for style. forecast-api is its own independent uv
	# project now (own venv/lockfile, not a workspace member -- its
	# restructured package is named `app`, same as data-pipeline's, so
	# sharing one workspace venv would collide the two), so it's linted
	# via its own venv rather than the root `$(UV) run`.
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run --directory services/forecast-api ruff check .
	# Run type-checking per service
	$(UV) run mypy services/data-pipeline/app
	$(UV) run --directory services/forecast-api mypy app
	# Run security checks
	$(UV) run bandit -r services/data-pipeline/app services/forecast-api/app

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
	# forecast-api is its own independent uv project (own venv/lockfile),
	# so it's tested via its own venv rather than the root `$(UV) run`.
	$(UV) run --directory services/forecast-api pytest -m "not e2e" \
		--cov=app \
		--cov-fail-under=90
	$(UV) run pip-audit
	$(UV) run --directory services/forecast-api pip-audit

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

# ── ML ──────────────────────────────────────────────────────────────────────
.PHONY: train
train: ## Train the demand-forecast LSTM and log/register it in MLflow. Pass REGION=NSW1 to override.
	$(UV) run --package data-pipeline ecolens-pipeline train $(if $(REGION),--region $(REGION))

.PHONY: tune
tune: ## Small grid search over hidden_size/lr, each trial logged to MLflow. Pass REGION=NSW1 to override.
	$(UV) run --package data-pipeline ecolens-pipeline tune $(if $(REGION),--region $(REGION))

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