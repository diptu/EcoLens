# ecoLens forecast-api

Low-latency demand-forecast serving. Reads a single wide, pre-joined
row per region from the warehouse's `ml_features_demand_v1` mart
(built by `services/data-pipeline`'s dbt project) and returns a
point + P10/P90 forecast for the next N 30-minute slots. No joins are
issued at request time — the mart already carries everything needed
(lagged demand, rolling stats, weather, holiday flag) on one row per
`(region, ts_30)`, per `INGESTION.md`/`werehouse.md`'s three-layer
design.

## Boundary

Per the root `TODO.md`'s forecasting section: `data-pipeline` owns
model **training** and MLflow registration end-to-end; `forecast-api`
only ever **loads and serves**. No trained model is registered yet
(`ECO-108`..`ECO-119` are still backlog), so `v1` ships a seasonal-naive
baseline forecaster (`forecasting/baseline.py`) computed directly from
the mart's precomputed lag columns — a real, working default rather
than a stub, and the seam a future model-loader swaps into without an
API contract change.

## Run

Dev (single process, auto-reload):

```bash
cd services/forecast-api
uv sync
uv run uvicorn ecolens_forecast_api.main:app --reload --port 8003
# or from the repo root: make api
```

Production (Gunicorn supervising `UvicornWorker` processes — see
`gunicorn_conf.py` and `TODO.md`'s ECO-F01):

```bash
cd services/forecast-api
uv run gunicorn -c gunicorn_conf.py --chdir src ecolens_forecast_api.main:app
# or from the repo root: make api-prod
```

Worker count defaults to `(2 * CPU cores) + 1` (capped at 8); override
with `FORECAST_WEB_CONCURRENCY`. Each worker holds its own
`pg_min_pool`..`pg_max_pool` Postgres connections, so raising worker
count multiplies total DB connections — see `TODO.md`'s ECO-P02.

## Config

Env vars are prefixed `FORECAST_` (e.g. `FORECAST_PG_HOST`,
`FORECAST_REDIS_URL`) — see `settings.py`. Points at the same
`ecolens_warehouse` Postgres database the warehouse API reads, using
its own connection pool/cache tuning (same rationale as
`ingestion.storage.settings.MongoSettings` / `warehouse.api.settings.WarehouseApiSettings`
in `data-pipeline`: a distinct read surface shouldn't couple its
tuning to another service's).

## Test

```bash
cd services/forecast-api
uv run pytest
```
