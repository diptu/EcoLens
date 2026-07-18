# Data Pipeline Roadmap & Technical Debt

## 🚦 Status Legend
- `[ ]` Backlog: Not started
- `[/]` In Progress: Actively being addressed
- `[!]` Blocker: Prevents production stability/scaling
- `[✓]` Completed

---

## 🏗 Core Libraries & Architecture
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-D01]** | P1 | Backend | Add `db/session.py` — async Postgres session factory (asyncpg + SQLAlchemy async), mirrors `forecast-api`'s session module. |
| `[ ]` | **[ECO-D02]** | P1 | Backend | Add `cache/redis_client.py` — async Redis client + circuit-breaker factory. |
| `[!]` | **[ECO-D03]** | P0 | Backend | Add `pipeline/circuit_breaker.py` — Redis-backed circuit breaker (closed/open/half-open) guarding all external API calls. |
| `[ ]` | **[ECO-D04]** | P1 | Backend | Add `pipeline/landing.py` — `land_to_s3` / `load_to_postgres` helpers (MinIO + Postgres round-trip). |
| `[ ]` | **[ECO-D05]** | P2 | Backend | Add `observability/metrics.py` — Prometheus counters/histograms + metrics server. |
| `[ ]` | **[ECO-D06]** | P2 | Backend | Wire settings additions — `s3_*`, `bom_api_key`, `bom_stations`, `model_train_epochs`, `model_train_lr`. |

## 📥 Ingestion Pipelines
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[!]` | **[ECO-I01]** | P0 | Backend | OpenElectricity SDK wrapper + `ingest_openelectricity` task + CLI wiring (`ingest oe`). |
| `[!]` | **[ECO-I02]** | P0 | Backend | AEMO NEM 5-min dispatch fetcher (resample to 30-min; per-region NSW1/QLD1/VIC1/SA1/TAS1). |
| `[ ]` | **[ECO-I03]** | P1 | Backend | AEMO WEM (SWIS) 30-min fetcher. |
| `[ ]` | **[ECO-I04]** | P1 | Backend | BoM weather observation fetcher (6 stations, station→region mapping). |
| `[ ]` | **[ECO-I05]** | P2 | Backend | AEMO holidays calendar ingest (7 regions). |
| `[ ]` | **[ECO-I06]** | P2 | Backend | `scripts/backfill.py` — resumable, idempotent historical backfill CLI. |
| `[ ]` | **[ECO-I07]** | P1 | Backend | Ingest test suite (circuit breaker, landing round-trip, OE integration test). |

## 🧱 Warehouse (dbt)
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-W01]** | P1 | Backend | Staging models — `stg_aemo_nem_dispatch`, `stg_aemo_wem_dispatch`, `stg_openelectricity_mix`, `stg_bom_observations`, `stg_aemo_holidays`, `dim_station`. |
| `[ ]` | **[ECO-W02]** | P1 | Backend | Intermediate models — `int_demand_with_weather`, `int_mix_share`, `int_carbon_intensity`. |
| `[ ]` | **[ECO-W03]** | P1 | Backend | Mart models — `fct_energy_demand` rewrite (incremental), `fct_emissions_5min`, `fct_carbon_intensity`, `dim_energy_mix`, `dim_facility`. |
| `[ ]` | **[ECO-W04]** | P2 | Backend | Macros — `cents_to_dollars`, `aest_now`, `classify_period`, `add_timescaledb_hypertable`. |
| `[ ]` | **[ECO-W05]** | P2 | Backend | TimescaleDB hypertable post-hook (idempotent) on `fct_energy_demand`. |
| `[ ]` | **[ECO-W06]** | P2 | Backend | Singular test — system-level carbon intensity within ±2% of NGER national avg. |
| `[ ]` | **[ECO-W07]** | P3 | Backend | dbt docs generation wired into CI (`make dbt-docs`). |

## 🤖 ML Pipeline
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-M01]** | P1 | Backend | `ml/data.py` — `DemandDataset` sliding-window dataset, per-region `StandardScaler`. |
| `[ ]` | **[ECO-M02]** | P1 | Backend | `ml/features.py` — lag/rolling + cyclical encoding, shared `FEATURE_COLUMNS`. |
| `[ ]` | **[ECO-M03]** | P1 | Backend | `ml/models/lstm.py` — `LSTMForecaster` (attention pooling, P50/P10/P90 heads). |
| `[ ]` | **[ECO-M04]** | P2 | Backend | `ml/training/losses.py` — Huber + Pinball + composite loss. |
| `[ ]` | **[ECO-M05]** | P1 | Backend | `ml/training/train.py` — Lightning training loop (AdamW, early stopping, MLflow logging). |
| `[ ]` | **[ECO-M06]** | P1 | Backend | `ml/training/trainer.py` — `train_one` orchestrator. |
| `[ ]` | **[ECO-M07]** | P2 | Backend | `ml/training/tune.py` — Optuna hyperparameter sweep (50 trials, median pruner). |
| `[ ]` | **[ECO-M08]** | P2 | Backend | `ml/evaluation/metrics.py` — MAPE/RMSE/MAE/PICP, vectorised. |
| `[ ]` | **[ECO-M09]** | P2 | Backend | `ml/evaluation/conformal.py` — MAPIE conformal calibration for P10/P90 bands. |
| `[ ]` | **[ECO-M10]** | P2 | Backend | `ml/evaluation/evaluate.py` — rolling walk-forward evaluation + JSON report. |
| `[ ]` | **[ECO-M11]** | P1 | Backend | `mlops/registry.py` — MLflow model registry wrapper (register/promote/load_production). |
| `[ ]` | **[ECO-M12]** | P1 | Backend | `mlops/promote.py` — gated promotion (rolling-28d MAPE comparison). |
| `[ ]` | **[ECO-M13]** | P2 | Backend | `mlops/drift.py` — PSI + KS drift detection, Evidently HTML report. (tracks root [ECO-102]) |

## ⚡ Performance & Observability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-P01]** | P2 | Backend | `/metrics` Prometheus exporter on the CLI worker (ingest rows, dbt build duration, ingest duration histograms). |
| `[ ]` | **[ECO-P02]** | P3 | Backend | Prometheus scrape config for `data-pipeline:9090`. |
| `[ ]` | **[ECO-P03]** | P3 | Backend | Grafana dashboard (`infra/grafana/dashboards/data-pipeline.json`). |

## 🧪 Testing & Runbooks
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-T01]** | P1 | Backend | `tests/conftest.py` — Postgres/MinIO/MLflow testcontainers fixtures. |
| `[ ]` | **[ECO-T02]** | P1 | Backend | Unit tests — features, metrics, circuit breaker. |
| `[ ]` | **[ECO-T03]** | P1 | Backend | Integration tests — 4 ingesters, dbt build, train pipeline, promote, drift, backfill. |
| `[ ]` | **[ECO-T04]** | P3 | Backend | Runbooks — `docs/runbooks/data-pipeline.md`, `docs/runbooks/etl.md`. |

## 🛠 Operations
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-O01]** | P2 | Backend | `scripts/backup-mlflow.sh` — daily SQLite backup + MinIO mirror, 7-day pruning. |
| `[ ]` | **[ECO-O02]** | P2 | Backend | `scripts/cleanup.sh` — weekly VACUUM, hypertable chunk pruning, log pruning. |
| `[ ]` | **[ECO-O03]** | P2 | Backend | `scripts/promote_model.sh` — daily cron wrapper for `ml promote`. |
| `[ ]` | **[ECO-O04]** | P1 | Backend | `scripts/smoke_test_pipeline.sh` — end-to-end health check (ingest→dbt→train), used in CI + first deploy. |
| `[ ]` | **[ECO-O05]** | P2 | Backend | `mlops/health.py` — registry/run/production health check, consumed by `forecast-api`'s `/v1/readyz`. |

## ✨ Polish
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-X01]** | P3 | Backend | `make data-validate` CI target (schema validation gate). |
| `[ ]` | **[ECO-X02]** | P3 | Backend | README data-pipeline section + dbt DAG diagram. |
| `[ ]` | **[ECO-X03]** | P3 | Backend | `make show-lineage` target (opens dbt docs). |
| `[ ]` | **[ECO-X04]** | P3 | Backend | Record W4 demo (ingest → dbt → train → register → promote). |

---

## 📝 Developer Guidelines
1. **Link:** Every item must have a corresponding GitHub Issue.
2. **Format:** Use `[ECO-XXX]` in code comments and dbt model docs to enable audit scripts.
3. **Definition of Done (DoD):**
    - Code change implemented and reviewed.
    - Associated unit/integration tests passed (`make test-pipeline` green).
    - This file updated (Status moved to `[✓]`).
    - GitHub Issue closed.
    - `TODO` tag removed from source code.

---

## ✅ Recently Completed
- [✓] **[ECO-D00]** Scaffold `data-pipeline` package — `pyproject.toml`, `cli.py` Click group stubs, `config.py` (pydantic-settings), `observability/logging.py` (structlog).
- [✓] **[ECO-D96]** Container + orchestration wiring — multi-stage distroless Dockerfile, docker-compose service (Postgres + MinIO deps), Makefile targets (`pipeline-cli`, `train`, etc.).
- [✓] **[ECO-W00]** dbt project scaffold — `dbt_project.yml`, `emissions_factors.csv` seed, first `fct_energy_demand.sql` mart.
- [✓] **[ECO-D99]** `docs/dev-plan-backend.md` — 6-week backend delivery plan.
