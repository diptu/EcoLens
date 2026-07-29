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
| `[✓]` | **[ECO-P03]** | P2 | TBD | Benchmarked dynamic quantization vs. plain fp32 via `scripts/benchmark_inference.py` (default `hidden_size=128`, `num_layers=2`, `lookback=48`, 200 iterations, Apple Silicon/qnnpack): p50 latency **regressed** 3.05ms → 6.65ms (0.46x, i.e. 2.2x *slower*), p99 6.71ms → 9.78ms, peak RSS delta ~0 either way. `DemandLSTM` at this size is too small for quantize/dequantize overhead to pay for itself. Result: don't enable it — see ECO-F07. |

---

## 🔮 Forecasting Pipeline (Model Serving)
> `forecast-api` never trains — `data-pipeline` owns training, tuning,
> evaluation, conformal calibration, and MLflow registration end-to-end (root
> `TODO.md` ECO-108–119; `forecasting/mlops/registry.py` = ECO-115). This
> service's job is the "CPU-Edge" half of `strategy.md`'s hybrid pattern:
> load whatever model version currently holds the registry's `production`
> alias, serve it at low latency behind the *same* response contract the
> baseline forecaster already ships, and hot-swap in new versions without
> downtime.
>
> **ECO-F02–F06 are done** — this whole path was actually implemented and
> tested (101 passing tests) well before this checklist was updated to say
> so; it just silently kept serving the ECO-F00 baseline in every real
> environment because of two unrelated bugs, both now fixed: (1)
> `forecasting/loader.py` imports `mlflow.pytorch`, which unconditionally
> imports `pandas` — `mlflow-skinny` deliberately excludes it and this
> service's `pyproject.toml` never declared it directly, so importing the
> loader raised `ModuleNotFoundError` in any environment that hadn't
> incidentally installed pandas some other way; (2) `.env`'s `FORECAST_PG_DSN`
> pointed at a Neon project (`ep-little-mountain`) that predated this
> session's rotation to the project (`ep-noisy-water`) `data-pipeline`'s
> warehouse actually writes to, *and* used that project's `-pooler` endpoint,
> which (same issue `data-pipeline`'s own `NEON_DSN` hit) doesn't reliably
> propagate the search_path `queries.py`'s un-schema-qualified
> `ml_features_demand_v1` reference depends on. Also found and fixed while
> verifying live: the model version that happened to hold the `production`
> alias (v7, trained 2026-07-23) had a saved `scaler.json` fit against a
> 24-feature set from before this repo's `FEATURE_COLUMNS` list dropped to
> 23 — a real, separate bug on the *training* side (see root `TODO.md`), not
> this service's fault, but it meant every real forecast request 500'd until
> a fresh, consistent model version was trained and promoted.

| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[✓]` | **[ECO-F02]** | P1 | — | `Settings` has `mlflow_tracking_uri`, `model_alias` (default `"production"` — an MLflow registry alias, not the deprecated numeric-stage API this item's description originally assumed), `model_reload_interval_seconds`, and CPU-only inference (no `inference_device` toggle needed — this service never targets anything but CPU). |
| `[✓]` | **[ECO-F03]** | P1 | — | `forecasting/loader.py`'s `ModelLoader.load_current()` resolves `client.get_model_version_by_alias(...)` and loads the `state_dict` artifact (not the full pickled model — see `data-pipeline`'s `registry.py` docstring for why) with `map_location="cpu"`. |
| `[✓]` | **[ECO-F04]** | P1 | — | `forecasting/reload.py`'s `ModelReloader` polls every `model_reload_interval_seconds` and atomically swaps `self.state` so in-flight requests never see a half-loaded model. |
| `[✓]` | **[ECO-F05]** | P1 | — | `queries.get_recent_feature_rows()` + `forecasting/features.build_window()` reconstruct the `model_lookback`-length window per request. Still a plain Postgres query, not the `collections.deque` streaming buffer this item originally specified — fine at current traffic; revisit only if per-request Postgres reads become a measured bottleneck. |
| `[✓]` | **[ECO-F06]** | P1 | — | `routes.py`'s `/v1/forecast/{region}` serves real LSTM output (`forecasting/lstm_forecast.py`, conformal-calibrated P10/P50/P90) when `reloader.state.current` is set, falling back to the ECO-F00 baseline otherwise (no model loaded, or not enough history for a newly-onboarded region) — same `ForecastResponse` contract either way, distinguished only by the `model` field (`demand_lstm_v{version}` vs `seasonal_naive_v1`). |
| `[✓]` | **[ECO-F07]** | P2 | TBD | Decided, per ECO-P03's benchmark: leave `inference_optimization` at its default (`"none"`). Dynamic quantization made this model's inference *slower*, not faster (0.46x p50), so there's no reason to wire it in or migrate `optimize.py` off the deprecated `torch.quantization.quantize_dynamic` API — the whole quantization path stays dead code (already load-bearing-free: `loader.py` calls `apply_inference_optimization` unconditionally, but it's a no-op at the default setting). ONNX Runtime / JIT trace weren't benchmarked — only worth revisiting if a future, larger model (e.g. TFT) makes CPU inference latency an actual bottleneck; re-benchmark on real deploy hardware (this run was Apple Silicon/qnnpack, not the x86/fbgemm path production would likely use) if that happens. |
| `[✓]` | **[ECO-F08]** | P2 | — | (partial) `reload.py`'s `_sanity_check` runs a dummy forward pass and rejects a candidate whose output isn't finite (NaN/Inf), keeping the previous version and setting `last_reload_success=False`/`last_reload_error` instead of swapping — tested (`test_sanity_check_rejects_a_broken_candidate_and_keeps_serving_the_old_one`). **Not done**: broader failure conditions the original item also named (e.g. a latency regression) — still an open question per `reload.py`'s own comment and `strategy.md` §7. |
| `[ ]` | **[ECO-F09]** | P3 | TBD | Once `data-pipeline` resolves root TODO ECO-118 (what "online learning" means — periodic fine-tune vs. scheduled full retrain), revisit `model_reload_interval_seconds`: a fine-tune-every-few-minutes design needs a much tighter reload loop than a nightly retrain does. |

---

## 🧪 Testing & Observability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[✓]` | **[ECO-T01]** | P2 | — | `test_forecasting_loader.py` is a real integration test against a real local MLflow tracking store (sqlite + tmp_path artifact dir, same pattern `data-pipeline`'s own `test_forecasting_registry.py` uses) — the actual cross-service contract (data-pipeline writes the `state_dict`/`model_architecture.json` artifacts, this service reads them with zero knowledge of `data-pipeline`'s `DemandLSTM` class), not a mocked stand-in. |
| `[✓]` | **[ECO-T03]** | P1 | — | `/health`'s `model` block reports `loaded`/`version`/`last_reload_at`/`last_reload_success`/`last_reload_error` from `ModelReloader.state` — verified live: correctly showed `loaded: false` before a working model was promoted, and `loaded: true, version: "<n>"` after. |
| `[✓]` | **[ECO-T04]** | P2 | — | `test_forecasting_reload.py::test_reload_picks_up_a_promoted_second_version` covers exactly this: two versions registered against a real local registry, hot-reload swaps to the second. `test_in_flight_reference_survives_a_concurrent_reload` additionally covers the "without dropping in-flight requests" half. |

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
