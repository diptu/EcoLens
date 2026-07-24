# Forecast API Roadmap & Technical Debt

## 🚦 Status Legend
- `[ ]` Backlog: Not started
- `[/]` In Progress: Actively being addressed
- `[!]` Blocker: Prevents production stability/scaling
- `[✓]` Completed

---

## 📦 Baseline Serving Layer (v1, live on `main`)
`main` now has a real `src/ecolens_forecast_api/`: FastAPI app factory +
lifespan, this service's own `Settings` (`FORECAST_*` env prefix, same
pattern as `data-pipeline`'s `MongoSettings`/`WarehouseApiSettings`), an
async Postgres pool (`asyncpg`, not SQLAlchemy) reading `data-pipeline`'s
`ml_features_demand_v1` mart, a Redis response cache that no-ops safely when
unconfigured, a `/health` endpoint, region/horizon request validation,
optional API-key auth, structured event-style logging, and a real (not
stubbed) seasonal-naive forecaster (`forecasting/baseline.py`) that computes
point + naive P10/P90 bands straight from the mart's precomputed lag/rolling
columns — plus a 59-test suite covering all of it (see ECO-F00 below).

Everything else in this file builds on top of that baseline (ECO-F00/F01/F99,
all done — see "Recently Completed") and assumes those files exist — read
them before touching `settings.py`, `routes.py`, or `forecasting/baseline.py`.

See `strategy.md` for the model-loading design this baseline is the
foundation for.

---

## 🏗 Architectural Debt
_None open right now — see "Recently Completed" below (ECO-F01)._

## ⚡ Performance & Scalability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-P02]** | P2 | TBD | Tune the `asyncpg` pool (`pg_min_pool`/`pg_max_pool`/`pg_command_timeout_seconds` in `settings.py`) under real load once this service is deployed — it ships reasonable defaults (2–10 connections) but they're unvalidated against actual `/v1/forecast` traffic. (Previously worded as "optimize SQLAlchemy async session scoped context" — inapplicable; this service doesn't use SQLAlchemy anywhere, it's raw `asyncpg`.) |
| `[ ]` | **[ECO-P03]** | P2 | TBD | Benchmark the CPU inference optimization picked in ECO-F07 (quantized/ONNX/JIT) against the plain fp32 model — p50/p99 latency and RSS memory — before it ships. See `strategy.md` §5/§7. |

---

## 🔮 Forecasting Pipeline (Model Serving)
> `forecast-api` never trains — `data-pipeline` owns training, tuning,
> evaluation, conformal calibration, and MLflow registration end-to-end (root
> `TODO.md` ECO-108–119; `forecasting/mlops/registry.py` = ECO-115). This
> service's job is the "CPU-Edge" half of `strategy.md`'s hybrid pattern:
> load whatever model version is currently tagged `Production` in the MLflow
> Registry, serve it at low latency behind the *same* response contract the
> baseline forecaster already ships, and hot-swap in new versions without
> downtime.
>
> Ordered so each item is buildable once the one before it lands. **Blocked**
> on `data-pipeline` shipping ECO-115 (registry) and ECO-114 (conformal
> intervals) — there is nothing to load or serve real bands from until a
> model is actually registered there. Until then, `/v1/forecast/{region}`
> keeps serving the ECO-F00 baseline; nothing here should regress it.

| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-F02]** | P1 | TBD | Extend this service's existing `Settings` with model-loader config: `mlflow_tracking_uri`, `model_stage` (default `"Production"`), `model_reload_interval_seconds`, `inference_device` (`"cpu"`), and a flag for whichever CPU optimization ECO-F07 picks. |
| `[ ]` | **[ECO-F03]** | P1 | TBD | Build the Model Loader: pull the current `model_stage`-tagged version via `mlflow.pytorch.load_model(...)` against the registry, loading with `map_location=torch.device('cpu')` (`strategy.md` §3). Blocked on `data-pipeline` registering at least one model version (ECO-115). |
| `[ ]` | **[ECO-F04]** | P1 | TBD | Build hot-reload: poll the registry every `model_reload_interval_seconds` and atomically swap the in-memory model reference so in-flight requests never see a half-loaded model (`strategy.md` §4, "Synchronization"). Polling vs. a push signal from `data-pipeline` on promotion is still open — see `strategy.md` §7. |
| `[ ]` | **[ECO-F05]** | P1 | TBD | Build the sliding-window feature buffer (`collections.deque`, `strategy.md` §6) that reconstructs each request's `model_lookback`-length input window from already-ingested features, so `/v1/forecast` doesn't re-query Postgres per request beyond the single latest-row read the baseline already does. |
| `[ ]` | **[ECO-F06]** | P1 | TBD | Swap the baseline forecaster for real model output behind the existing `/v1/forecast/{region}` contract (`ForecastResponse`/`ForecastStep` in `models.py` — no route or schema change for API consumers), adding `data-pipeline`'s conformal calibration (ECO-114) for real P10/P50/P90 bands in place of the baseline's naive std-based ones. |
| `[ ]` | **[ECO-F07]** | P2 | TBD | Decide + implement one CPU inference optimization from `strategy.md` §5 (dynamic quantization, ONNX Runtime, or JIT trace) — pick based on the benchmark in ECO-P03, not all three. |
| `[ ]` | **[ECO-F08]** | P2 | TBD | Add rollback: if a newly-loaded model version fails a post-reload sanity check (e.g. NaN output, latency spike), keep serving the previous version and alert instead of swapping. Exact trigger condition is still open — `strategy.md` §7. |
| `[ ]` | **[ECO-F09]** | P3 | TBD | Once `data-pipeline` resolves root TODO ECO-118 (what "online learning" means — periodic fine-tune vs. scheduled full retrain), revisit `model_reload_interval_seconds`: a fine-tune-every-few-minutes design needs a much tighter reload loop than a nightly retrain does. |

---

## 🧪 Testing & Observability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-T01]** | P2 | @Nazmul | Integration test coverage for the MLflow registry integration once ECO-F03 lands (currently nothing to test — no model loader exists on `main`). |
| `[ ]` | **[ECO-T03]** | P1 | TBD | Extend `/health` (already reports Postgres + Redis status) with the currently-loaded model version, last successful reload time, and last reload failure if any — feeds the model-reload metric ECO-T02 deferred. Blocked on ECO-F03/F04. |
| `[ ]` | **[ECO-T04]** | P2 | TBD | Integration test: point the model loader (ECO-F03) at a real (test) MLflow registry, register two model versions, and confirm hot-reload (ECO-F04) picks up the second without dropping in-flight requests. |

---

## 📝 Developer Guidelines
1. **Link:** Every item must have a corresponding GitHub Issue.
2. **Format:** Use `[ECO-XXX]` in code comments to enable audit scripts.
3. **Definition of Done (DoD):**
    - Code change implemented and reviewed.
    - Associated unit/integration tests passed.
    - This file updated (Status moved to `[✓]`).
    - GitHub Issue closed.
    - `TODO` tag removed from source code.

---

## ✅ Recently Completed
- [✓] **[ECO-T02]** (partial — see below) Added `metrics.py` + `GET /metrics` (unauthenticated, like `/health`): a request-latency histogram labeled by region and a cache-result counter (`hit`/`miss`/`disabled`), wired into the `/v1/forecast/{region}` handler. Multiprocess-safe, not just single-process-correct: `gunicorn_conf.py` now sets `PROMETHEUS_MULTIPROC_DIR` before workers fork and marks dead workers' shards via the `child_exit` hook, since this service defaults to multiple Gunicorn workers (ECO-F01) and `prometheus_client`'s plain registry is per-process — verified live with 2 real workers under `make api-prod`: each wrote its own `.db` shard, and a scrape correctly summed to the true cross-process total (20/20 requests), not just whichever worker answered the scrape. **Not done**: the model-reload success/failure counter ECO-T02 also asked for — no model loader exists yet (ECO-F04), so that counter would just permanently read zero; deferred to land alongside ECO-F04 instead of shipping a metric with no real event source. Added `prometheus-client` as a dependency.
- [✓] **[ECO-F01]** Added `gunicorn_conf.py`: Gunicorn as process manager, `uvicorn_worker.UvicornWorker` (the `uvicorn.workers.UvicornWorker` this service's pinned `uvicorn>=0.51.0` shipped is gone from that package — moved to the separate `uvicorn-worker` package) as the ASGI worker. Worker count defaults to `(2 * CPU cores) + 1` capped at 8 (each worker holds its own `pg_min_pool..pg_max_pool` connections, so an uncapped CPU-derived count would multiply DB connections unreasonably on a big box), overridable via the new `FORECAST_WEB_CONCURRENCY` setting. Bind host/port read from the existing `Settings` rather than duplicated as separate Gunicorn env vars. `make api` (dev, `--reload`) is unchanged; added `make api-prod` for this path. Verified live: booted 2 workers, `/health` served real traffic on a bound port, clean shutdown, no orphan processes. `services/forecast-api/pyproject.toml` gained `gunicorn`/`uvicorn-worker` as direct dependencies (were only present transitively via the root project before).
- [✓] **[ECO-F00]** Merged/ported the baseline FastAPI serving prototype into `main`: `app.py`, `settings.py`, `db.py`, `cache.py`, `routes.py`, `dependencies.py`, `validation.py`, `models.py`, `logging.py`, `forecasting/baseline.py`, and the full test suite (59 tests). Added `services/forecast-api` to the root `pyproject.toml` workspace members, fixed the stale `make api` target (was pointing at `ecolens.api.main:app`, a data-pipeline module that doesn't exist — now runs `ecolens_forecast_api.main:app` via `uv run --package forecast-api`), and fixed a latent pytest collection bug this exposed: `.claude/worktrees/` (which still holds a parallel copy of these same test files on their source branch) wasn't excluded from root `norecursedirs`, so `make test` from the repo root collided on same-named test modules. Full `make lint` + `make test` pass clean workspace-wide: ruff, mypy, bandit, 546 tests, 92% combined coverage, no known vulnerabilities (pip-audit).
- [✓] **[ECO-P01]** Redis caching layer for `/v1/forecast/{region}` (`cache.py`, wired into `routes.py`; no-ops safely when Redis is unconfigured/unreachable) — shipped as part of ECO-F00.
- [✓] **[ECO-F99]** CI already covers this service with no extra wiring needed: `.github/workflows/main.yml` runs `make lint`/`make test`, and the `Makefile` already special-cased `services/forecast-api/src` (skipping mypy/bandit gracefully when it had no `.py` files) — so once ECO-F00 added real files and workspace membership, CI picked it up automatically. No separate GitHub Actions job was needed.

<!-- STRUCTURE:START (auto-generated by services/scripts/update_structure_todos.sh — do not edit by hand) -->
### 🗂 Structure

_Auto-generated by `services/scripts/update_structure_todos.sh`. `[ ]` = empty stub file, `[x]` = has content. Re-run after adding/removing files to keep this current — do not hand-edit between the markers._

- [ ] `src/ecolens_forecast_api/__init__.py`
- [x] `src/ecolens_forecast_api/app.py`
- [x] `src/ecolens_forecast_api/cache.py`
- [x] `src/ecolens_forecast_api/db.py`
- [x] `src/ecolens_forecast_api/dependencies.py`
- [ ] `src/ecolens_forecast_api/forecasting/__init__.py`
- [x] `src/ecolens_forecast_api/forecasting/baseline.py`
- [x] `src/ecolens_forecast_api/forecasting/features.py`
- [x] `src/ecolens_forecast_api/forecasting/loader.py`
- [x] `src/ecolens_forecast_api/forecasting/lstm_forecast.py`
- [x] `src/ecolens_forecast_api/forecasting/model.py`
- [x] `src/ecolens_forecast_api/forecasting/optimize.py`
- [x] `src/ecolens_forecast_api/forecasting/reload.py`
- [x] `src/ecolens_forecast_api/logging.py`
- [x] `src/ecolens_forecast_api/main.py`
- [x] `src/ecolens_forecast_api/metrics.py`
- [x] `src/ecolens_forecast_api/models.py`
- [x] `src/ecolens_forecast_api/queries.py`
- [x] `src/ecolens_forecast_api/routes.py`
- [x] `src/ecolens_forecast_api/settings.py`
- [x] `src/ecolens_forecast_api/validation.py`
<!-- STRUCTURE:END -->
