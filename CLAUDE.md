# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository reality check

The README describes the **target** architecture (3 services, dbt, MLflow, PyTorch LSTM, Next.js dashboard). The actual repo is much earlier stage — read code, not the README, to know what exists:

- **`services/data-pipeline`** is the only service with real code. It's a `uv` workspace member of the root `pyproject.toml`.
- **`services/forecast-api`** and **`services/dashboard`** are not yet built (forecast-api has only `pyproject.toml`/`TODO.md`, no `src/`; dashboard doesn't exist yet despite being referenced in docs).
- Several files that look load-bearing are **empty stubs**: `docker-compose.yml`, `.github/workflows/ci.yml`, `.env.example`, `SECURITY.md`, `services/data-pipeline/src/ecolens/shared/config.py`, `services/data-pipeline/src/ecolens/api/app.py`. The working `docker-compose copy.yml` at the repo root has the real service definitions (postgres, redis, minio, mlflow, prefect, api, web, prometheus, grafana, loki) — check whether it's meant to replace `docker-compose.yml` before relying on `make up`.
- `services/data-pipeline/src/ecolens/config.py` is the real, working settings module; `shared/config.py` is an empty duplicate — don't import from it.
- `services/data-pipeline/src/ecolens/ingestion/storage/mongo.py` is currently scratch/broken code (calls `Settings.get_settings()`, a classmethod that doesn't exist — `get_settings()` is a module-level function). Don't assume it works; check before building on it.
- Ingestion TODO scope lives in `services/data-pipeline/TODO.md` (currently HTML-commented out) and `services/data-pipeline/src/ecolens/ingestion/INGESTION.md` (design doc for the Mongo → Postgres `raw.*` pipeline — read this before touching ingestion code).

## Commands

All commands run from the repo root unless noted. The workspace uses `uv`; there is no top-level `npm`/`pnpm` project yet (no dashboard).

```bash
make bootstrap        # uv sync --all-extras --all-groups + pre-commit install
make lint              # ruff check + ruff format --check + mypy (forecast-api & data-pipeline src) + bandit
make test              # pytest -m "not e2e" + pip-audit
make up / make down    # docker compose -f docker-compose.yml up/down (currently empty — see note above)
make api                # uvicorn ecolens.api.main:app --reload (forecast-api — not yet implemented)
make audit              # scripts/audit_todos.sh — checks TODO.md tag hygiene
make list-todos         # prints all [ECO-*]/[ING-*] tagged TODOs across services
```

Per-service, since each service has its own `pyproject.toml`/`uv.lock`:

```bash
cd services/data-pipeline
uv sync
uv run pytest                          # run all tests
uv run pytest tests/path/test_x.py::test_name   # single test
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run python scripts/test_mongo_connection.py  # standalone Mongo connectivity smoke test (ING-0901)
```

Integration tests are opt-in: set `RUN_INTEGRATION=1` before running pytest (see `services/data-pipeline/TODO.md` ING-0902).

mypy is configured at the **root** `pyproject.toml` with `mypy_path` pointing at both services' `src/` and `explicit_package_bases = true` — run it from the repo root when checking cross-service typing, not from inside a service directory.

## Architecture

### Monorepo layout

Each service under `services/*` has its own `pyproject.toml`, `uv.lock`, README, and (eventually) its own Dockerfile/CI lane. The root `pyproject.toml` declares a `uv` workspace with `services/data-pipeline` as a member (forecast-api is not yet a workspace member). Shared/root-level concerns: `Makefile`, `.pre-commit-config.yaml` (ruff, mypy, bandit — scoped to `services/**/*.py`), root `TODO.md` for cross-service items tagged `[ECO-*]`.

### data-pipeline internal structure

Package root: `services/data-pipeline/src/ecolens/`

- **`config.py`** — single `Settings(BaseSettings)` (pydantic-settings), cached via `get_settings()` (`@lru_cache`). Loads from `.env` + env vars, fields cover Postgres, MongoDB, Redis, S3/MinIO, MLflow, upstream API tunables, ML/training hyperparameters, and drift-detection thresholds. This is the pattern to follow for any new config — don't invent a second settings object unless it's genuinely a different deployable (see the `MongoSettings` exception below).
- **`ingestion/`** — the part of the pipeline with real design intent (see `INGESTION.md`). Three-layer flow: **External API → MongoDB (raw) → PostgreSQL `raw.*` (structured) → dbt**. MongoDB is upserted via unique compound keys per source (e.g. `region + ts` for AEMO NEM) so retries are idempotent; every doc gets `ingest_run_id`, `fetched_at`, `source` stamped on write.
  - `ingestion/storage/settings.py` — `MongoSettings`, a **separate** `BaseSettings` from the global `Settings`, deliberately independent so the ingestion layer's Mongo tuning (pool size, retry policy, per-collection names, circuit-breaker thresholds) doesn't couple to the rest of the service. Has `collection_for_source()` / `unique_key_for_source()` helpers — this is the intended way to look up per-source Mongo config, not hardcoding collection names at call sites.
  - `ingestion/sources/` — one module per upstream (AEMO NEM, AEMO WEM, BoM, OpenElectricity, holidays).
  - `ingestion/validators/` — pandera schemas per source, validate after normalize, before upsert.
  - `ingestion/circuit_breaker.py` — per-source breaker shared across FastAPI + CLI ingestion paths.
- **`forecasting/`** — LSTM demand model code (models, training/tuning, evaluation incl. conformal prediction, mlops registry/promotion/drift, serving). This mirrors the design in the root README's "ML pipeline" section but check actual file contents before assuming a given function exists — much of this tree may be scaffolding.
- **`warehouse/`** — dbt project lives at `warehouse/dbt_project/` (staging/intermediate/marts), plus a `runner.py` to invoke dbt from Python.
- **`shared/`** — cross-cutting: `db/session.py` (Postgres), `cache/redis_client.py`, `observability/logging.py` (structured logger, event-style: `log.info("mongo.client_created", uri_host=..., db_name=...)` — thin stdlib wrapper, no structlog dependency), `observability/metrics.py`.
- **`api/`** — FastAPI app for the data-pipeline's own control surface (trigger ingestion, check run status) — distinct from `forecast-api`, the separate public-facing service. `api/app.py` is currently empty.

### TODO tagging convention

Work items across the repo use per-scope ID prefixes so audit tooling (`scripts/audit_todos.sh`, `make audit`/`make list-todos`) can find them: `[ECO-XXX]` (root/cross-service, and forecast-api uses `[ECO-Fxx]`/`[ECO-Pxx]`/`[ECO-Txx]`), `[ING-XXXX]` (data-pipeline ingestion layer only, see `services/data-pipeline/TODO.md`). When adding a TODO tag in code, it must have a matching row in the relevant `TODO.md` or the audit script will flag it; when you resolve one, remove the tag from source and flip the row to `[✓]`.

### Config pattern to follow

New settings go on the existing `Settings` class in `config.py` unless they belong to a genuinely separate deployable/tuning surface (the `MongoSettings` precedent). Access via the cached `get_settings()` factory, never by instantiating `Settings()` directly at import time in application code (tests may construct it directly to override fields).
