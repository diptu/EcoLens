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
	# Run type-checking per service
	$(UV) run mypy services/forecast-api/src services/data-pipeline/src
	# Run security checks
	$(UV) run bandit -r services/forecast-api/src services/data-pipeline/src

.PHONY: test
test: check-env ## Run test suite with security checks.
	$(UV) run pytest -m "not e2e"
	$(UV) run pip-audit

# ── Services ────────────────────────────────────────────────────────────────
.PHONY: api
api: ## Run API locally.
	$(UV) run uvicorn ecolens.api.main:app --reload

.PHONY: web
web: ## Run Next.js (requires pnpm).
	cd services/dashboard && pnpm dev

# ── Release ─────────────────────────────────────────────────────────────────
.PHONY: deploy
deploy: ## Deploy with target validation.
	@if [ -z "$(DEPLOY_TARGET)" ]; then echo "Usage: make deploy DEPLOY_TARGET=prod"; exit 1; fi
	@echo "Deploying to $(DEPLOY_TARGET)..."
	bash scripts/deploy.sh $(DEPLOY_TARGET)
