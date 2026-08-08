# Todo's

**Audit pass (2026-08-08, "ultrathink")**: every checkbox below was re-verified against the actual codebase (not assumed from names/docstrings) via 4 parallel service audits. `[x]` = confirmed real and working. `[ ]` with a `(partial: ...)` note = something real exists but doesn't fully meet the item as written — the note says exactly what's there and what's missing. Bare `[ ]` = confirmed absent. `services/data-pipeline` no longer exists on disk (intentionally deleted 2026-08-08, decommission complete) — any evidence below that references it is from git history, not a live file.

## Ingestion todo's

Here is a comprehensive, production-grade to-do list for building the **Ingestion Service Backend**, broken down into logical engineering phases based on your system architecture.

---

## Phase 1: Project Initialization & Infrastructure Setup

* [x] **Repository & Environment Structure**: Initialize the Python project structure (using Poetry or Hatch) with modular separation for API clients, workers, models, and storage interfaces.
* [x] **Configuration Management**: Implement a typed configuration system (e.g., Pydantic `BaseSettings`) for environment variables, API endpoints, credentials, and connection strings.
* [x] **Dockerization** — closed 2026-08-08: `infra/docker/ingestion.Dockerfile` is now real multi-stage (`builder` runs `uv sync`, `runtime` starts fresh from `python:3.12-slim` and only `COPY --from=builder`s the finished `.venv` + source — no `uv`/`uvx` binaries or dependency-resolution intermediates in the shipped image). Verified with a real `docker build` + `docker run ... health` (`{"status":"ok"}`), not just a lint pass. Root `docker-compose.yml` still has real `ingestion`/`ingestion-worker`/`ingestion-beat` service blocks, a shared `duckdb_staging` named volume, and a healthchecked `rabbitmq` service.

---

## Phase 2: External API Integration & Scheduling

* [x] **Robust HTTP Client** — closed 2026-08-08: new `app/service/pipeline/http_retry.py` adds `DEFAULT_LIMITS` (`httpx.Limits(max_connections=10, max_keepalive_connections=5)`, applied to every `httpx.AsyncClient(...)` construction site) and `fetch_with_retry` (jittered exponential backoff — same style `duckdb_staging.py`'s existing `_connect_rw_with_retry` already uses — retrying `httpx.TransportError` and 5xx `HTTPStatusError`, never a 4xx). Wired into the 3 real (non-placeholder) fetch paths: AEMO NEM's and AEMO WEM's Archive-day loops, and BoM's live per-station fetch. 5 new tests (`tests/test_http_retry.py`) plus the existing per-source suites, all passing. The Redis-backed `CircuitBreaker` (fail-fast) stays too — it's a different, complementary layer (breaker trips across *repeated* run failures; retry recovers *within* one run from a single transient blip), not replaced by this.
* [x] **Celery Core Setup**: `app/celery_app.py` — `Celery("ecolens_ingestion", broker=settings.rabbitmq_url, backend=settings.redis_url, ...)`.
* [x] **Celery Beat Schedulers** (superseded by an explicit later decision, not a gap): only a single unified 30-minute schedule exists today — the module's own comment records this replaced the earlier per-source 5/15/30-minute cadences "per an explicit request" on 2026-08-05. Re-adding a 5-minute task would directly undo that deliberate choice, not close a gap — left as-is.
* [~] Configure a 5-minute cron/interval task for high-frequency operational energy data. — intentionally superseded, see above; not implemented, and shouldn't be without a new explicit decision to reverse the 2026-08-05 one.
* [x] Configure a 30-minute cron/interval task for lower-frequency datasets. — `ingest-all-sources`, `crontab(minute="*/30")`.


* [x] **Asynchronous Task Workers**: `ingest_all_sources_task` fans out via `celery.group(ingest_source_task.si(key,...) for key in SOURCES)` — independent child tasks, one failing source can't block others.

---

## Phase 3: Staging & Cloud Storage Layer

* [x] **DuckDB Staging Interface**: `app/service/pipeline/duckdb_staging.py` (`stage_dataframe`/`read_staged`/`delete_staged`, `_connect_rw_with_retry` with jittered backoff for lock contention).
* [x] **Normalization Pipeline**: e.g. `ingest_openelectricity.py`'s `_pivot_long_to_wide` normalizes OE's long-form payload into the wide `raw.openelectricity_mix` schema.
* [x] **Cloudflare R2 Integration**: `app/service/object_storage.py` — `aioboto3` S3-compatible client, gated by `Settings.object_storage_configured` (R2 vs. local MinIO fallback).

---

## Phase 4: Hybrid Anomaly Detection Layer

* [x] **Rule-Based Engine**: `app/service/pipeline/anomaly.py` — physical-range checks (`_BOUNDS`), missing-value checks, z-score spike detection.
* [x] **ML/Heuristic Scoring**: `app/service/pipeline/ml_anomaly.py` — per-source `IsolationForest`, trained on DuckDB history, calibrated via `decision_function` percentile.
* [x] **Metadata Enrichment**: `anomaly.detect_anomalies` returns `anomaly_score`/`anomaly_reason` alongside the original, unmodified record; flagged rows persist separately to `meta.anomalies`.

---

## Phase 5: Event-Driven Messaging (RabbitMQ)

* [x] **RabbitMQ Publisher**: `app/db/rabbitmq.py::publish_landed_event`, called from `_common.standard_run` after staging + anomaly scan complete.
* [x] **Event Payload Schema** — closed 2026-08-08: `window_start`/`window_end` (the exact same values already written to `meta._ingest_log`) now ride along in the published payload too — `None`/`None` for a plain scheduled/manual run (honest, not fabricated), real ISO timestamps for a backfill run. A consumer no longer has to cross-reference `meta._ingest_log` by `run_id` just to learn the range a landed event covers. 2 tests in `tests/test_common.py` (the plain-run `None` case, and a new backfill-shaped test asserting the real values propagate).
* [x] **Fault Tolerance & Dead-Letter Queues (DLQ)** (real fault tolerance; DLQ correctly N/A here, not a gap): `aio_pika.connect_robust` gives connection recovery, and aio_pika channels carry publisher confirms by default. A DLQ is fundamentally a *consumer-side* concept (where to put a message a handler rejected) — this service never consumes anything, only publishes, so there's no queue here to attach one to. `services/waerehouse`'s consumer already has a real one (`app/db/rabbitmq.py`'s application-level DLX/DLQ) for exactly this queue. Nothing to build on this service's side.

---

## Phase 6: Observability, Logging, & Testing

* [ ] **OpenTelemetry Instrumentation**: confirmed absent — no `opentelemetry-*` dependency anywhere in this service.
* [x] **Structured JSON Logging**: `app/core/logging.py` — structlog + JSON renderer, `run_id`/`request_id` bound via contextvars; `source`/`run_id` logged on every ingest event.
* [x] **Unit & Integration Testing** (real coverage, via `monkeypatch` rather than `respx`/`responses`): 40+ test files covering anomaly detection, ML anomaly scoring, DuckDB staging transactions, the RabbitMQ client, and Celery task/beat dispatch. `pyproject.toml`'s dev deps have `pytest`/`pytest-cov`/`anyio` but not `respx`/`responses` — external APIs are mocked by monkeypatching internal fetch functions instead.
* [x] Write unit tests for data normalization and anomaly detection rules using `pytest`.
* [~] Write integration tests utilizing `respx` or `responses` to mock external REST APIs. — real API-mocking coverage exists, just via `monkeypatch` instead of `respx`/`responses` specifically.
* [x] Test local DuckDB transactions and Celery task execution pipelines.



## werehouse todos

Here is a comprehensive, production-grade to-do list for building the **Event-Driven Warehousing Service Backend**, structured around your architecture specifications.

---

## Phase 1: Warehouse Infrastructure & Schema Design

* [x] **NeonDB Serverless Connection Setup**: `app/core/config.py`'s `Settings.database_url` (normalizes `postgresql://`→`+asyncpg`, `sslmode=`→`ssl=`); `app/db/session.py`'s `get_engine()` uses `pool_pre_ping=True` + `statement_cache_size=0` (the real fix for Neon's connection pooler).
* [x] **Database Schema Architecture**:
* [x] Create the `raw.*` schema to house immutable, unedited payloads matching external API structures. — `app/migrations/0001_raw_schema.sql`, 5 immutable tables.
* [x] Create staging and analytical schemas (e.g., `staging.*`, `mart.*` or curated tables) to host transformed data. — `dbt_project.yml` maps `staging`→schema `staging`, `marts`→schema `marts`.


* [x] **Migration & Version Control Setup** (raw SQL, not Alembic — explicitly allowed by this item's own wording): `app/migrations/0001-0003_*.sql` + `scripts/apply-migrations.sh`. Note: some schema history originates from the now-deleted `services/data-pipeline`'s own earlier migrations (`0002-0006_raw_*.sql`) — those are recoverable from git history (`git show 6d0b5cb:services/data-pipeline/migrations/...`) but no longer exist as live files in this repo; the schema they created is unaffected.

---

## Phase 2: Event Consumer & Ingestion Synchronization

* [x] **RabbitMQ Event Consumer**: `app/db/rabbitmq.py::consume_landed_events` — `aio_pika.connect_robust`, manual ack, `prefetch_count=1`, application-level DLX/DLQ; `app/consumers/landed_events.py::sync_landed_event` is the handler.
* [x] **Data Extraction Pipeline**: `sync_landed_event` calls `app.db.duckdb_client.read_run_with_fallback` (DuckDB read with an R2 fallback).
* [x] **Raw Data Loader (`raw.*`)**: `app/loaders/postgres_loader.py::load_to_postgres` — COPY into a temp table, then `INSERT ... ON CONFLICT DO NOTHING` into `raw.*`.
* [x] **Idempotency & Error Handling**: natural-key PKs drive the `ON CONFLICT DO NOTHING`; `app/loaders/ingest_log.py` (`mark_synced`/`mark_sync_failed`) tracks `meta._ingest_log` status; failures publish to the app-level DLQ and always ack (no infinite redelivery loop).

---

## Phase 3: dbt (Data Build Tool) Project Configuration

* [x] **dbt Core Initialization**: `dbt/ecolens/dbt_project.yml` + `dbt/ecolens/profiles.yml` (postgres adapter, env-var driven).
* [x] **Source Definitions (`schema.yml`)**: `dbt/ecolens/models/staging/_sources.yml` — `raw.*` (5 tables) + `meta.anomalies`, each with `loaded_at_field`/`freshness` (except `aemo_holidays`, intentionally).
* [x] **Staging Models Layer (`stg_*.sql`)**: 6 models under `dbt/ecolens/models/staging/`.
* [x] **Intermediate & Mart Models**: `int_carbon_intensity`/`int_mix_share`/`int_fuel_emissions`/`int_demand_with_weather` (intermediate); `fct_generation_mix`/`fct_energy_demand`/`fct_carbon_intensity`/`fct_emissions_5min`/`dim_energy_mix`/`dim_facility` (marts).

---

## Phase 4: Data Quality, Testing, & Documentation

* [x] **dbt Built-in Tests**: `not_null`/`unique`/`accepted_values`/`relationships` across `_staging__models.yml`/`_marts__models.yml`/`_intermediate__models.yml` — 51 tests total.
* [x] **Custom Data Tests** — closed 2026-08-08: `tests/assert_generation_mix_sums_near_total.sql` (the 5 generation buckets must sum to within 10%/50 MW of `total_generation_mw` — catches an entire fuel silently dropping out, the direction the pre-existing `assert_generation_buckets_within_total.sql` doesn't cover) and `tests/assert_demand_mw_non_negative.sql` (`demand_mw` can't drop below -100 MW). **Live-verified against a real disposable Postgres 16 container**: seeded synthetic `raw.*` data, ran a real `dbt build` — both new tests pass against healthy data (89/90 total, the 1 failure is the pre-existing documented `assert_national_intensity_within_tolerance` placeholder, unrelated); then injected a sign-flipped demand row and a fuel-bucket dropped to 0, re-ran `dbt build` — both new tests correctly failed with exactly 1 result each; reverted the bad data, confirmed both pass again. Not just "compiles," confirmed to actually catch what they're meant to.
* [x] **Source Freshness Configuration**: `warn_after`/`error_after` declared per source in `_sources.yml` (README notes live freshness checks only started running reliably recently — configuration itself is real).
* [x] **Automated Documentation** — closed 2026-08-08: `ecolens-warehouse dbt docs generate` already worked (the existing generic `dbt <subcommand>` passthrough), it just had no automation or documentation. `.github/workflows/ci.yml`'s `warehouse-dbt` job now runs it right after `dbt test` passes and uploads the static site as a build artifact (`dbt-docs`, 30-day retention) on every push/PR. **Live-verified**: `ecolens-warehouse dbt docs generate` against the same disposable Postgres produced a real `target/index.html` (dbt's own catalog+manifest-driven site). README documents both the CI artifact and the local `dbt docs serve` workflow.

---

## Phase 5: Pipeline Execution & Orchestration

* [x] **DuckDB-to-PostgreSQL Pipeline Wrapper**: `app/consumers/landed_events.py` orchestrates DuckDB read → Postgres load; `app/dbt/runner.py::run_dbt` shells out to the dbt CLI against Postgres.
* [x] **Scheduled Execution Runner** — closed 2026-08-08: a real `dbt build` now fires automatically off the back of new data actually landing. New `app/dbt/scheduler.py` (`run_build`/`trigger_build_if_due`, refactored out of `POST /v1/dbt/build`'s own inline logic so both the HTTP route and this new path share one lock-acquire/run/log sequence) is called from `consumers/landed_events.py`'s `sync_landed_event` after every successful sync — fire-and-forget (`asyncio.ensure_future`, never blocks the consume loop), debounced by `Settings.scheduled_build_min_interval_minutes` (15 min default, tighter than ingestion's own 30-min Celery Beat cadence) so 5 sources landing in one ingestion cycle don't queue 5 back-to-back builds. **Live-verified against a real disposable Postgres**: called `run_build`/`trigger_build_if_due` directly — a real `dbt build` ran and logged to `meta._dbt_build_log` (`trigger=manual_verify`), and an immediate second `trigger_build_if_due` call correctly returned `False` (debounce working against real timestamps). 14 new tests (`test_dbt_scheduler.py`, `test_landed_events.py`'s new `TestScheduledBuildTrigger`).
* [x] **Retention & Storage Policy Automation**: `app/retention/pruning.py` (60-day window), `vacuum.py`, `size_monitor.py`, `cold_storage.py` (R2 export before delete) — CLI: `prune`/`vacuum`/`check-size`/`export-and-prune`.
* [] **free storage** : use Celery Beat to trigger a daily script that drops postgresql data older than 60 days.

---

## Phase 6: Observability, Logging, & Maintenance

* [x] **OpenTelemetry Tracing** — closed 2026-08-08: `opentelemetry-api`/`-sdk`/`-exporter-otlp-proto-grpc` added; `app/core/tracing.py`'s `configure_tracing()`/`get_tracer()` (real no-op when `Settings.otel_traces_enabled` is `False`, the default — same "optional infra, real no-op when absent" pattern R2/`object_storage_configured` already uses here; batch-exports OTLP to `services/observility`'s already-configured Collector, `:4317`, when enabled). Real spans wrap the 2 operations the item names: `consumers.landed_events.sync_landed_event` (`warehouse.sync_landed_event`, tagged `source`/`table`/`run_id`/`rows_loaded`) and `dbt.scheduler.run_build` (`warehouse.dbt_build`, tagged `trigger`/`triggered_by`/`exit_code`) — both record real exceptions/error status, not just a bare span. Wired into both `app.main`'s lifespan (API process) and the CLI's `main()` group callback (`consume`/`dbt` commands' own process). 5 new tests (`test_tracing.py`). This closes the cross-service Phase 1 gap's warehouse half too (root `TODO.md`'s Observability section) — ingestion/forecast-api still have none.
* [x] **Structured JSON Logging**: `app/core/logging.py` (structlog, JSON renderer, `run_id`/`request_id` contextvars), used throughout consumers/loaders/retention.
* [ ] **Performance Indexing & Monitoring** (partial, deliberate not accidental): no dedicated secondary/BRIN indexes exist — `0001_raw_schema.sql`'s own header comment explains the design relies solely on composite `PRIMARY KEY` btree indexes (`ts` leading column) for range deletes/lookups instead. Not changed this pass — no live query-plan evidence (`EXPLAIN ANALYZE` against real production-scale data) justifies a specific new index yet, and adding one speculatively would be premature optimization against a design the schema's own migration already reasoned through.


## Forcasting todos

Here is a comprehensive, production-grade to-do list for building the **Predictive Modeling & Carbon Insights (Forecasting) Service Backend**, structured around your architecture and adaptive AI specifications.

---

## Phase 1: Environment, Dependencies & MLflow Infrastructure Setup

* [x] **ML & Deep Learning Environment**: PyTorch (`torch>=2.13.0`) and TimesFM (`timesfm[torch]>=2.0`, which pulls in `huggingface-hub` transitively) are real direct dependencies. `app/service/ml/device.py`'s `get_device()` (CUDA → MPS → CPU) is now wired into every from-scratch training loop (`ml/train.py`'s `train_model`, `ml/train_tft.py`'s `train_tft_model`, `ml/train_energy_forecast.py`'s `train_energy_model` — `ml/incremental.py`/`incremental_tft.py`/`ml/tune.py` all delegate to these, so they're covered too) — model + every batch now move to whatever accelerator is actually available, where previously training silently ran CPU-only regardless of hardware. Checkpoints/MLflow artifacts are moved back to CPU before being persisted (`log_and_register_run`/`log_and_register_energy_run`), matching `docs/training-strategy.md`'s "Model Portability Strategy" every load site already assumes. Serving/inference deliberately stays CPU-only by design (`device.py`'s own docstring) — single-request inference doesn't benefit from a GPU round-trip the way a full training run does. Still no TensorFlow anywhere, no direct Hugging Face `transformers` dependency (both remain considered-and-declined, no real use case).
* [x] **MLflow Tracking Server Setup**: `app/core/config.py`'s `mlflow_tracking_uri` + `app/service/mlops/tracking.py`'s `configure_mlflow()`. Artifact store (MinIO/S3) is configured at the MLflow server/docker-compose level, not hardcoded in this service.
* [x] **Model Registry Setup**: `app/service/mlops/registry.py` (stage transitions) + `app/service/ml/registry.py`'s `promote_version` — gates Production promotion on a real `test_mape` comparison and an `eval_gate_passed` tag, rejecting via `PromotionRejected` otherwise.

---

## Phase 2: Data Pipeline & Feature Engineering Integration

* [x] **Feature Store / Data Loader**: `app/service/ml/data.py`'s `load_latest_window`/`load_training_data` query `raw_marts.fct_energy_demand` directly.
* [x] **Time-Series Windowing Pipeline**: `app/service/ml/features.py` — lags (1,2,3,6,12), rolling mean/std (6/12/24), cyclical hour/day/month encodings.
* [ ] **Streaming Inference Buffer**: confirmed absent, deliberately not built this pass — the only "streaming" code is `app/api/v1/stream/routes.py`'s WebSocket, which just re-reads the latest DB row every 5 minutes; no in-memory or Redis-backed sliding buffer, no online-learning feed exists. `ml/data.py`'s `load_latest_window` already re-queries Postgres fresh on every single inference call (its own docstring: "inference only ever needs the single most recent window, not a sliding-window dataset") — this is a real request/response batch-serving architecture, not a true online/streaming pipeline, so a buffer here would sit alongside that per-request DB read rather than replacing it, duplicating state nothing would actually consume. Worth building if/when inference volume or latency genuinely demands avoiding the per-request round-trip; not assumed here.

---

## Phase 3: Adaptive Multi-Model Architecture & Incremental Learning

* [x] **Base Model Implementation**:
* [x] Implement/configure deep learning architectures (LSTM for short-term memory dependencies, Temporal Fusion Transformer [TFT] for multi-horizon complex feature interactions). — `app/models/ml.py`'s `DemandLSTM`, `app/models/tft.py`'s `DemandTFT` (hand-rolled, a documented decision vs. `pytorch-forecasting`).
* [x] Integrate Google's **TimesFM** foundation model for zero-shot or fine-tuned time-series forecasting. — `app/models/timesfm_adapter.py`, wraps `google/timesfm-2.5-200m-pytorch`, zero-shot.


* [x] **Online & Incremental Learning Engine**: `app/service/ml/incremental.py`'s `train_and_register_incremental` (warm-starts from Staging/Production weights, lighter epochs/LR) + `app/service/ml/divergence.py`'s catastrophic-forgetting drift guard.
* [x] **Ensemble Weighting Layer**: `app/service/ml/blend.py`'s `blend_forecasts`/`BlendForecaster` — inverse-recent-MAPE weighting, recomputed from real re-forecast windows.

---

## Phase 4: Probabilistic Forecasting & Conformal Calibration

* [x] **Quantile Loss / Multi-Output Heads**: `app/service/ml/losses.py` — pinball loss + Huber loss combined for P10/P50/P90 heads.
* [x] **Conformal Calibration Layer**: `app/service/ml/conformal.py`'s `ConformalCalibration` — real CQR, per-horizon-step `q` widening, persisted as an MLflow artifact.
* [x] **Self-Correction & Fallback Mechanism**:
* [x] Build automated safety checks to widen or tighten uncertainty bounds if error rates drift out of bounds. — `app/service/ml/adaptive_calibration.py`: real Adaptive Conformal Inference (Gibbs & Candès 2021), simplified to one scalar interval-width multiplier per `(model_name, region)`, updated by `forecast_reconciliation.py`'s reconciliation sweep from real observed coverage (did the actual demand value land inside what was served) — a miss widens the scale, a hit narrows it back toward 1.0 (never below `MIN_SCALE`/above `MAX_SCALE`). `api/v1/forecast/routes.py`'s `_run_single_region_forecast` applies the current scale symmetrically around `p50` before every response is cached/served (`region == "NEM"` excluded, same aggregate-of-5-regions scope limit the fallback below documents). Live-tested (`tests/test_adaptive_calibration.py`, `tests/test_forecast_reconciliation.py`'s coverage tests, `tests/test_forecast.py`'s `test_applies_the_adaptive_calibration_scale_to_the_served_interval`).
* [x] Program an instantaneous fallback mechanism to switch live inference to a pre-validated statistical baseline model if anomaly scores or failure spikes trigger in the primary models. — now live-wired (previously not): `app/service/ml/forecast_breaker.py`'s circuit breaker is driven by `forecast_reconciliation.py`'s background sweep (`watch_and_reconcile`, `app/main.py`'s lifespan), and `api/v1/forecast/routes.py`'s `get_forecast` checks `breaker.state` *before* the cache lookup, branching to `_run_baseline_fallback_forecast` (the same `BaselineForecaster` the walk-forward eval harness scores every model against) when open, reporting it honestly via `ForecastResponse.served_by`. `region == "NEM"` (5 independently-breakered regions summed) is a documented, deliberate scope exclusion — always serves the real model.



---

## Phase 5: Model Optimization, Pruning & Lifecycle Management

* [x] **Structured Pruning Workflow**: `app/service/ml/prune.py` — real structured pruning of `DemandLSTM` (correctly handles the LSTM's 4-gate row-blocks, physically compacts tensors; LSTM-only by explicit design, TFT/TimesFM excluded).
* [x] **Post-Pruning Fine-Tuning**: same file's `prune_and_recover` (`recovery_epochs`, `recovered_run_id`/`recovered_test_mape`, reuses `train_model`).
* [x] **Automated MLflow CI/CD Promotion**: `app/service/ml/evaluate.py`'s `run_live_evaluation_gate` (fresh walk-forward backtest, tags `eval_gate_passed`/`eval_gate_mape`) feeds `promote_version`'s gate.

---

## Phase 6: Carbon Insights & Environmental Accounting Engine

* [x] **Carbon Intensity & Generation Mapping**: `app/service/ml/carbon_engine.py`'s `CarbonEngine.calculate` (generation × per-source emission factor), fed by `app/service/ml/emission_factors.py`'s real, volume-weighted factors from `dim_energy_mix`.
* [x] **Renewable Proportion Derivation**: `app/service/ml/data.py`'s `resolve_intensity_method` — falls back from `live_provider` to derived `live_mix_weighted` when the provider figure is missing/stale (gated by `emissions_provider_freshness_minutes`).
* [x] **Emissions Aggregator**: `app/api/v1/emissions/routes.py` (`/v1/emissions`, `/ytd`, `/current`, `/timeseries`, `/forecast`) + `app/api/v1/forecast_intelligence/routes.py` — both output combined demand+emissions figures.

---

## Phase 7: Serving API, Observability, & Production Integration

* [x] **Inference API (FastAPI)**: `app/api/v1/forecast/routes.py`'s async `get_forecast` — Redis-cached, real P10/P50/P90.
* [x] **OpenTelemetry Instrumentation**: `opentelemetry-api`/`-sdk`/`-exporter-otlp-proto-grpc` are now real direct dependencies. `app/core/tracing.py` (`configure_tracing()`/`get_tracer()`, real no-op when `Settings.otel_traces_enabled=False`, the default) is wired into both `app/main.py`'s lifespan and `app/cli.py`'s `main()` group callback. Real spans: `forecast_api.get_forecast` (region/served_by/model_version/forecast_horizon/inference_duration — `api/v1/forecast/routes.py`) and `forecast_api.check_drift` (anchor_found/anchor_run_id/relative_l2_drift/exceeded_threshold — `ml/divergence.py`). Exports OTLP-grpc to `services/observility`'s Collector, matching `services/waerehouse`'s identical pattern.
* [x] **Structured Logging**: `api/v1/forecast/routes.py`'s `get_forecast` now logs a `forecast.served` event with real `model_version`/`forecast_horizon`/`inference_duration`/`served_by`/`region` fields on every cache-miss (a cache hit has no inference to report — its own `cache="hit"` Prometheus label already covers that case). Prometheus metrics/response bodies still carry this data too, deliberately — the log line is additive, not a replacement.


## Observability todos

Here is a comprehensive, production-grade to-do list for building the **Centralized Observability Service**, structured around your architecture specifications and OpenTelemetry standards.

**Scope note**: `services/observility` itself is a pure Docker Compose stack (Prometheus/Grafana/Loki/Tempo/Alertmanager/OTel Collector/Promtail/cAdvisor) with no application code of its own — items below that depend on the 3 business services (ingestion/waerehouse/forecast-api) actually emitting telemetry are genuinely gated on those services, not on anything this stack itself is missing.

---

## Phase 1: OpenTelemetry SDK & Microservice Instrumentation

* [x] **OpenTelemetry Core SDK Integration** — all 3 services closed 2026-08-08: `services/ingestion`, `services/waerehouse`, and `services/forecast-api` each have real `opentelemetry-api`/`-sdk`/`-exporter-otlp-proto-grpc`, exporting to this stack's own Collector. Ingestion's `app/core/tracing.py` is wired into `main.py`'s lifespan, `cli.py`'s `main()` group (skipped specifically for the `worker` subcommand — Celery's prefork pool forks from that process, and a live gRPC exporter channel doesn't survive `fork()` safely; `celery_app.py`'s `worker_process_init` configures it fresh in each forked child instead), and instruments `pipeline.tasks._common.standard_run`'s whole run-start/fetch/anomaly-scan/stage/publish lifecycle as one `ingestion.standard_run` span. See waerehouse/forecast-api's own `TODO.md`s for their sides (RabbitMQ sync handler + dbt build wrapper; `get_forecast` serving path + `check_drift`'s drift guard).
* [~] **Distributed Trace Propagation** — one of two real cross-service hops closed 2026-08-08, live-verified end-to-end: `app.db.rabbitmq.publish_landed_event` (ingestion) injects the current span's W3C `traceparent` into the AMQP message headers (`opentelemetry.propagate.inject`); `consume_landed_events` (warehouse) extracts it (`opentelemetry.propagate.extract`) and attaches it as the current context for the `handler(payload)` call, so `sync_landed_event`'s own span parents onto it. Verified against a real disposable RabbitMQ broker + this stack's own Collector/Tempo (not mocked): published trace id `155b3e7c746d7a90f010aaf2c2cbe5af`'s `ingestion.standard_run` span and the consumed `warehouse.sync_landed_event` span came back from Tempo's own `GET /api/traces/{id}` with the latter's `parentSpanId` exactly matching the former's `spanId` — a real, linked, two-service trace. The **second** hop (`services/waerehouse` → RabbitMQ → `services/forecast-api`'s training-trigger consumer) is **not** instrumented this pass — `training_worker.py`'s consume path still starts (if anything) an unlinked span.
* [~] **Custom Metrics Instrumentation** (uneven across services, improved 2026-08-08):
* *Ingestion*: `ingest_runs_total`/`ingest_duration_seconds`/`ingest_rows_total`/`latest_ingest_ts`/`circuit_breaker_state` plus two new ones — `anomaly_flags_total{source}` (incremented in `standard_run` per flagged row) and `http_poll_duration_seconds{source}` (timed around `pipeline.http_retry.fetch_with_retry`'s whole retry loop, the real "API-polling-latency" signal this item used to lack).
* *Warehouse*: strong real coverage — `dbt_run_duration_seconds`/`dbt_runs_total`/`rows_loaded_total`/`queue_message_age_seconds` (a real sync-latency proxy).
* *Forecasting*: `forecast_predictions_total`/`forecast_prediction_latency_seconds` plus two new ones — `forecast_drift_score{model_name}` (set by `ml/divergence.py`'s `check_drift`) and `forecast_prediction_error_pct{model_name,region}` (observed by `ml/forecast_reconciliation.py`'s `reconcile_pending_forecasts`, the same `error_pct` that already drives the circuit breaker, now also its own distribution). Still marked `[~]` rather than `[x]`: these are real but genuinely narrow (one drift metric, one error-rate metric) against the item's broader "instrument model execution routines... with OpenTelemetry traces" framing, which Phase 1's tracing work (not metrics) covers separately.
* All three services do export `ecolens_build_info{service,version}`.

* [x] **Structured Logging Integration**: each service's `core/logging.py` gained two new structlog processors, `_static_fields` (binds `service`/`environment`/`version` on every line — `environment` a new `Settings.environment` field, `"development"` default matching `prometheus.yml.template`'s own hardcoded label) and `_add_trace_context` (reads whatever span is current at each individual log call and adds `trace_id`/`span_id` hex fields — can't be a one-time contextvars bind like `request_id`/`run_id` since it has to vary line-by-line with whatever span is open). Live-confirmed as part of the Distributed Trace Propagation verification above: the consumer process's own `tracing.enabled` log line came back with real `service="warehouse"`, `environment="development"`, `version="0.1.0"` fields.

---

## Phase 2: Centralized OpenTelemetry Collector Pipeline

* [ ] **Collector Architecture Design** (partial, deliberate): `otel/otel-collector-config.yml` is traces-only by design — metrics flow via direct Prometheus scrape instead, per this stack's own documented architecture. Not a gap in the collector itself, but means the "centralized gateway for all telemetry" framing in this item isn't literally how it works.
* [x] **Receiver Configuration**: OTLP grpc `:4317` + http `:4318` both configured.
* [x] **Processor Pipeline**: `memory_limiter` (256 MiB soft/64 MiB spike, checked every 1s) now runs first in the traces pipeline, ahead of `batch` — live-verified by actually starting the real `otel/opentelemetry-collector-contrib:0.110.0` image against this exact config (`docker logs`: `"Memory limiter configured"` + `"Everything is ready"`). No attribute-filtering processor added, deliberately — nothing this stack's 3 services currently emit needs redacting/filtering, so adding one would be unexercised config, not a real gap.
* [ ] **Exporter Routing** (partial): traces→Tempo is wired (`otlp/tempo` exporter) plus a `debug` stdout exporter. Metrics→Prometheus happens via direct scrape, not through this collector (by design). Logs→Loki go via Promtail, not this collector at all — there is no logs pipeline in `otel-collector-config.yml`.

---

## Phase 3: Telemetry Storage Backends Setup

* [x] **Prometheus Setup**: `prometheus/prometheus.yml.template` (rendered via an `envsubst` init container) + a healthchecked `docker-compose.yml` service on port 9091, retention env-driven.
* [x] **Grafana Loki Setup**: `loki/loki-config.yml`, filesystem storage, retention via `${LOKI_RETENTION_PERIOD}`.
* [x] **Grafana Tempo Setup**: `tempo/tempo-config.yml`, OTLP receiver, local block storage, retention via `${TEMPO_RETENTION}`.

---

## Phase 4: Grafana Dashboards & Centralized Visualization

* [x] **Infrastructure & System Health Dashboard**: `grafana/dashboards/platform.json` (6 panels), auto-provisioned.
* [x] **Data Pipeline & Ingestion Dashboard**: `grafana/dashboards/ingestion.json` (7 panels), auto-provisioned.
* [x] **Warehousing & Transformation Dashboard**: `grafana/dashboards/warehouse.json` (9 panels), auto-provisioned.
* [x] **Predictive Modeling & Carbon Insights Dashboard**: `grafana/dashboards/forecast.json` (9 panels), auto-provisioned. Note: panels backed by traces or drift/P10-90-error metrics will render empty until Phase 1's OTel/metrics gaps above close — expected, not broken.

---

## Phase 5: Alerting Rules & Incident Response Integration

* [x] **Metric Alert Rules**: `prometheus/rules/{ingestion,warehouse,forecast,platform,rabbitmq}.yml` — 19 real alerts (e.g. `IngestionHighFailureRate`, `ForecastLatencyHigh`, `WarehouseDbtRunFailures`, `RabbitMQQueueDepthHigh`) + 2 recording rules. All 5 rule files (and the rendered `prometheus.yml` that loads them) validated with `promtool check rules`/`check config` against the real `prom/prometheus:v2.54.1` image.
* [x] **Pipeline Health Alarms**: closed 2026-08-08 — `infra/docker/rabbitmq/enabled_plugins` enables `rabbitmq_prometheus` (real per-queue metrics, live-verified: created a queue via the management API, published a message, confirmed `rabbitmq_detailed_queue_messages{queue="..."}` incremented from 0 to 1 against the real image). `prometheus.yml.template` gained `rabbitmq`/`rabbitmq-queues` scrape jobs (the latter hits `/metrics/detailed?family=queue_coarse_metrics` for the per-queue labels the plain `/metrics` endpoint doesn't expose) + a new `RABBITMQ_TARGET` in `.env.example`. `prometheus/rules/rabbitmq.yml`'s `RabbitMQDeadLetterQueueNotEmpty`/`RabbitMQQueueDepthHigh` close the exact gap `ingestion.yml`'s own header comment used to flag.
* [ ] **Notification Channels** (partial): `alertmanager/alertmanager.yml.template` has a real, functional generic `webhook_configs` receiver (`ALERTMANAGER_WEBHOOK_URL`) with a critical-severity fast-repeat route — not a native Slack/PagerDuty integration, deliberately (the file's own header comment notes swapping in `slack_configs`/`pagerduty_configs` directly is the documented upgrade path if wanted).

---

## Phase 6: Infrastructure Isolation & Non-Blocking Pipeline Verification

* [x] **Asynchronous Transport Verification**: the collector's `batch` processor, Prometheus's pull-based scrape model, and Promtail's async Docker-socket reads mean nothing here can block a business service's own request path.
* [x] **Docker Deployment**: every service in `services/observility/docker-compose.yml` now has a real `deploy.resources.limits` (`cpus`/`memory`) block — sized per service's real role (Prometheus 1.0/1G as the heaviest steady-state consumer, one-shot `envsubst` init containers 0.25/128M, the OTel Collector 0.5/512M deliberately ~2x its own `memory_limiter`'s 256 MiB internal soft limit so that internal limiter — not the container's hard OOM kill — is what actually sheds load first). Validated with `docker compose config` against the real (non-swarm) `docker compose` CLI, which does apply `deploy.resources.limits` for plain `up`, not just swarm mode.
* [x] **End-to-End Trace Verification**: closed 2026-08-08, now that Phase 1's OTel gaps are (mostly) closed — live-verified against this stack's own real `otel-collector`/`tempo` containers (brought up via `docker compose up -d otel-collector tempo`, not mocked) plus a disposable RabbitMQ broker: a real `ingestion.standard_run` span (from `services/ingestion`) and a real `warehouse.sync_landed_event` span (from `services/waerehouse`), connected only by a real AMQP message round-trip, both landed in Tempo under the same trace id with the correct parent/child `spanId` relationship, retrieved via Tempo's own `GET /api/traces/{id}`. See Phase 1's "Distributed Trace Propagation" entry for the exact trace id and the one hop (warehouse → forecast-api's training trigger) this didn't cover.
