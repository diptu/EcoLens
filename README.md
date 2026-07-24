<div align="center">

# 🌱 ecoLens

### Near-real-time electricity demand forecasting & carbon-footprint intelligence for the Australian National Electricity Market.

**3 micro-services** · **Docker-first** · **Production-grade**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Services: 3](https://img.shields.io/badge/micro--services-3-2ea44f.svg)](docs/microservices-action-plan.md)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED.svg)](docker-compose.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type-checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![Next.js 15](https://img.shields.io/badge/Frontend-Next.js%2015-black.svg)](https://nextjs.org)
[![MongoDB 8.0+](https://img.shields.io/badge/mongodb-8.0%2B-green.svg)](https://www.mongodb.com/try/download/community)
[![Prefect](https://img.shields.io/badge/Orchestration-Prefect-024dfd.svg)](https://prefect.io)
[![PyTorch 2.x](https://img.shields.io/badge/ML-PyTorch%202.x-ee4c2c.svg)](https://pytorch.org)
[![MLflow](https://img.shields.io/badge/Tracking-MLflow-0194E2.svg)](https://mlflow.org)
[![dbt](https://img.shields.io/badge/Transform-dbt-FF694B.svg)](https://www.getdbt.com)
[![PostgreSQL 16](https://img.shields.io/badge/DB-PostgreSQL%2016-336791.svg)](https://www.postgresql.org)
[![Redis 7](https://img.shields.io/badge/Cache-Redis%207-DC382D.svg)](https://redis.io)
[![Security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![OpenSSF](https://img.shields.io/badge/OpenSSF-Scorecard-blue.svg)](https://scorecard.dev/viewer/?uri=github.com/diptu/ecoLens)

**ecoLens** turns raw AEMO and OpenElectricity data into operational carbon intelligence:
a PyTorch-LSTM demand forecaster, an emissions engine grounded in the live NEM/WEM
energy-mix, an end-to-end MLOps pipeline (dbt → MLflow → FastAPI → Redis → Postgres),
and a real-time Next.js dashboard.

[Overview](#-overview) ·
[Architecture](#-architecture) ·
[Quickstart](#-quickstart) ·
[ML Pipeline](#-ml-pipeline) ·
[API](#-api) ·
[Frontend](#-frontend) ·
[Deployment](#-deployment) ·
[Contributing](#-contributing)

</div>

---

## 📑 Table of contents

1. [Overview](#-overview)
2. [Why ecoLens?](#-why-ecolens)
3. [Key capabilities](#-key-capabilities)
4. [Architecture](#-architecture)
5. [Tech stack](#-tech-stack)
6. [Data sources](#-data-sources)
7. [Repository layout](#-repository-layout)
8. [Quickstart](#-quickstart)
9. [ML pipeline](#-ml-pipeline)
10. [API reference](#-api-reference)
11. [Frontend](#-frontend)
12. [Emissions model](#-emissions-model)
13. [Observability](#-observability)
14. [Testing](#-testing)
15. [Deployment](#-deployment)
16. [Performance & SLOs](#-performance--slos)
17. [Security](#-security)
18. [Roadmap](#-roadmap)
19. [Contributing](#-contributing)

> 📘 The full 3-service design, contracts, and rollout plan live in
> [`docs/microservices-action-plan.md`](docs/microservices-action-plan.md).
20. [License & attribution](#-license--attribution)
21. [Citation](#-citation)
22. [Maintainers](#-maintainers)

---

## 🌍 Overview

`ecoLens` is a **production-grade carbon-footprint platform** for Australian energy
consumers, analysts, and sustainability teams. It does three things, end-to-end:

1. **Forecasts short-term electricity demand** for every NEM region
   (NSW1, QLD1, VIC1, SA1, TAS1) and the WEM (SWIS, WA) with a multivariate
   PyTorch LSTM trained on AEMO historical dispatch data plus BoM weather covariates.
2. **Computes operational Scope-2 emissions** by combining the forecast (or
   live smart-meter data) with the **live NEM/WEM generation mix** sourced from
   [OpenElectricity](https://explore.openelectricity.org.au/energy/nem/),
   applying fuel-specific emissions intensity factors published by AEMO / DCCEEW.
3. **Exposes both as a near-real-time service** through a FastAPI backend
   (Redis-cached, Postgres-backed) and a Next.js 15 / TypeScript dashboard that
   refreshes on the AEMO 5-minute dispatch cycle.

The original `diptu/ecoLens` repo was a five-file FastAPI prototype. This rewrite is
the production refactor: typed end-to-end, containerised, traced, tested, and
deployable.

---

## 💡 Why ecoLens?

| Pain point | What ecoLens does |
| --- | --- |
| Carbon reports are lagging and back-of-envelope | Live, dispatch-interval emissions tied to the actual energy mix |
| No demand signal for procurement or sustainability planning | Multivariate LSTM demand forecast at 30-min / day / week horizons |
| ML is a notebook graveyard | dbt → MLflow → FastAPI → Next.js, all CI'd, all reproducible |
| Open data is scattered across AEMO, BoM, DCCEEW, OpenElectricity | One normalised warehouse, one canonical emissions model, one API |
| Australians don't have a clear Scope-2 number | Region-aware, fuel-mix-aware, unit-aware kgCO₂e/kWh figure |

---

## ✨ Key capabilities

- 🔮 **Demand forecasting** — multivariate PyTorch `nn.LSTM` with
  weather + calendar + price + lag features, supporting both
  point forecasts and conformal prediction intervals.
- ⚡ **Live emissions** — fuel-specific CO₂e intensity × generation, refreshed
  every 5 min from OpenElectricity's NEM endpoint, with WEM/SWIS fallback.
- 🧮 **Carbon footprint calculator** — user-entered kWh → kgCO₂e using the
  regional intensity at the time of consumption (or a chosen historical window).
- 📊 **Marts & analytics** — dbt models give you
  `fct_energy_demand`, `fct_emissions_5min`, `fct_carbon_intensity`,
  `dim_energy_mix`, `dim_facility` — queryable, tested, documented.
- 🛰️ **Real-time service** — FastAPI + Redis cache (60 s TTL on read paths)
  + Postgres (history) + Pydantic v2 schemas + OpenAPI 3.1.
- 🖥️ **Next.js 15 dashboard** — App Router, React Server Components,
  TanStack Query, Recharts, Tailwind, dark mode, full a11y.
- 🔁 **End-to-end MLOps** — Prefect/Airflow DAG ingests → dbt transforms →
  PyTorch trains → MLflow tracks/registers → model promoted via CI → served.
- 🔐 **Hardened** — non-root containers, SBOM, signed images, secret scanning,
  Bandit, Trivy, OpenSSF Scorecard, least-privilege IAM.

---

## 🏗️ Architecture

ecoLens is a **3-service micro-service system** — no more, no less. Two
user-facing services (the API and the dashboard) sit on an `edge` Docker
network; the data-pipeline worker is on the `internal` network only and is
never reachable from the public internet. All three share a small platform
of infra dependencies (Postgres, Redis, MinIO, MLflow, observability).

```
                ┌────────────────────────────────────────────────────┐
                │                       USERS                         │
                └─────────────────────────┬──────────────────────────┘
                                          │ HTTPS
                                          ▼
                            ┌──────────────────────────┐
                            │  ③  dashboard  (Next.js) │
                            │  :3000  • public         │
                            │  BFF routes → forecast-api│
                            └─────────────┬────────────┘
                                          │ /v1/* JSON
                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  ① forecast-api   (FastAPI)              ② data-pipeline  (Prefect)    │
│  :8000  • public / dev-only              headless  • internal only      │
│  • /v1/forecast, /v1/emissions,          • ingest AEMO / BoM / OE       │
│    /v1/footprint, /v1/healthz            • dbt build (raw → marts)      │
│  • loads LSTM from MLflow on boot        • train PyTorch LSTM          │
│  • Redis cache, Postgres read             • register model in MLflow    │
│                                                                         │
└────────────┬──────────────────┬───────────────────┬────────────────────┘
             │                  │                   │
             ▼                  ▼                   ▼
       ┌──────────┐       ┌──────────┐        ┌──────────────┐
       │ postgres │       │  redis   │        │  dbt   │
       │(data)    │       │  (cache) │        │  (transform)  │
       └────┬─────┘       └──────────┘        └────┬─────┘
            │                                      │
            └────────────────┬─────────────────────┘
                             ▼
                       ┌──────────┐
                       │  mlflow  │  ← model artifacts, params, metrics
                       │ (track)  │  ← forecast-api watches this; pipeline writes it
                       └──────────┘

  Platform infra (NOT services — no app code, no release cadence):
    postgres · redis · minio · mlflow · prometheus · grafana · loki
```

| # | Service | Port | Tier | Owns | Talks to |
|---|---|---|---|---|---|
| 1 | **`forecast-api`** | 8000 | edge | model serving, `/v1/*` contract, Redis cache, Postgres reads | `postgres`, `redis`, `mlflow` |
| 2 | **`data-pipeline`** | — | worker | AEMO/BoM/OE ingest, dbt, training, MLflow registration | `postgres`, `redis`, `minio`, `mlflow`, external APIs |
| 3 | **`dashboard`** | 3000 | edge | Next.js UI, BFF routes | `forecast-api` only |

**Key boundary rules:**

- `dashboard` never touches Postgres, Redis, or MLflow. It only calls `forecast-api`.
- `data-pipeline` never serves HTTP user traffic. It writes to the warehouse
  and registers the model in MLflow; `forecast-api` watches MLflow and
  hot-reloads the model. **No direct API call between the two.**
- The three services have **separate `pyproject.toml` / `package.json` files,
  separate Dockerfiles, separate CI jobs, and separate image tags**.

The full design rationale and rollout plan live in
[`docs/microservices-action-plan.md`](docs/microservices-action-plan.md).
A bigger Mermaid diagram lives in [`docs/architecture.md`](docs/architecture.md).

---

## 🧰 Tech stack

| Layer | Technology | Why |
| --- | --- | --- |
| Language | **python 3.12**, **TypeScript 5.x** | Strict typing end-to-end |
| ML | **PyTorch 2.x**, **Optuna**, **PyTorch Lightning** | LSTM + structured training loops |
| Data | **pandas 2**, **polars**, **numpy** | Polars for ingest, pandas for modeling |
| Warehouse | **PostgreSQL 16** + **TimescaleDB** | Time-series optimised hypertables |
| Transform | **dbt-core** + **dbt-postgres** | Tested, versioned SQL models |
| Tracking | **MLflow 2.x** | Experiment tracking + model registry |
| Orchestration | **Prefect 2** (or Airflow) | Schedules ingest, dbt, training, deploy |
| Serving | **FastAPI**, **Uvicorn**, **Pydantic v2** | Async, OpenAPI 3.1 |
| Cache | **Redis 7** | Forecast hot-path cache |
| Frontend | **Next.js 15**, **React 19**, **TanStack Query**, **Recharts**, **Tailwind 4**, **shadcn/ui** | RSC + streaming |
| Auth | **Auth.js** + OIDC (Keycloak / Auth0) | Standards-based |
| Containers | **Docker**, **distroless** final images | Small, secure |
| CI/CD | **GitHub Actions**, **Argo CD** (k8s) | PR checks → gitops |
| Observability | **OpenTelemetry**, **Prometheus**, **Grafana**, **Loki** | Traces + metrics + logs |
| Quality | **ruff**, **mypy**, **pytest**, **bandit**, **trivy** | Lint, type-check, test, scan |

---

## 📚 Data sources

| Source | What | Licence | How we ingest |
| --- | --- | --- | --- |
| [AEMO WEM](https://data.wa.aemo.com.au/) | Historical SWIS demand, generation, prices | AEMO open data | Scheduled CSV pull → S3 → dbt seed/staging |
| [AEMO NEM](https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem) | NEM dispatch (5-min) | AEMO open data | REST + MMS polling |
| [OpenElectricity (OpenNEM)](https://explore.openelectricity.org.au/energy/nem/) | Generation mix, emissions, price | CC BY-NC 4.0 | Official `openelectricity` Python SDK |
| [BoM](http://www.bom.gov.au/climate/data/) | Temperature, radiation | CC BY 3.0 AU | Scheduled API pull |
| [DCCEEW / NGER](https://www.dcceew.gov.au/energy/energy-data/national-greenhouse-and-energy-reporting) | Facility emissions factors | CC BY 4.0 | Seeded into `seeds/emissions_factors.csv` |
| [Electricity Maps – AU-WA](https://app.electricitymaps.com/datasets/AU-WA) | Hourly carbon intensity, WA | ODbL | Optional enrichment |

> **Attribution:** Wherever we publish a derived number, the upstream source is
> credited. See [`docs/data-sources.md`](docs/data-sources.md) for the full
> attribution and licence registry.

---

## 📁 Repository layout

A **3-service monorepo** — each service has its own `pyproject.toml` /
`package.json`, its own Dockerfile, and its own CI/deploy lane. Shared
infrastructure lives at the repo root; cross-service docs live in `docs/`.

```
ecoLens/
├── README.md                          ← you are here
├── LICENSE                            ← MIT
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── CODEOWNERS
├── docker-compose.yml                 ← local stack (3 services + 7 infra deps)
├── .env.example                       ← documented env vars
├── Makefile                           ← `make help` · per-service targets
│
├── services/                          ← the 3 micro-services
│   │
│   ├── forecast-api/                  ① SERVICE 1 / 3   — FastAPI
│   │   ├── pyproject.toml             (own deps: fastapi, pytorch, mlflow, redis, postgres)
│   │   ├── uv.lock
│   │   ├── README.md
│   │   ├── tests/
│   │   └── src/ecolens/
│   │       ├── api/                   main.py + routes + schemas + deps
│   │       ├── ml/                    model loading + inference
│   │       │   ├── models/lstm.py
│   │       │   └── registry.py        ← MLflow model loader (watches registry)
│   │       ├── emissions/             carbon math (factors, calculator, OE wrapper)
│   │       ├── db/                    SQLAlchemy 2.0 async (read-only role)
│   │       ├── cache/                 Redis client
│   │       ├── observability/         OTel, logging, metrics
│   │       └── cli.py                 `ecolens-api` console script
│   │
│   ├── data-pipeline/                 ② SERVICE 2 / 3   — Prefect worker
│   │   ├── pyproject.toml             (own deps: prefect, dbt, pytorch, mlflow, oe-sdk)
│   │   ├── uv.lock
│   │   ├── README.md
│   │   ├── tests/
│   │   ├── dbt/                       dbt project (mounted into container)
│   │   │   └── ecolens/
│   │   │       ├── dbt_project.yml
│   │   │       ├── models/{staging,intermediate,marts}/
│   │   │       └── seeds/emissions_factors.csv
│   │   ├── mlflow/projects/           MLflow Project entries for training runs
│   │   └── src/ecolens/
│   │       ├── pipeline/              Prefect flows + tasks
│   │       │   ├── flows/             daily_demand, retrain, drift_check
│   │       │   └── tasks/             ingest_aemo, ingest_bom, ingest_oe, …
│   │       ├── mlops/                 training, evaluation, registry promotion
│   │       ├── worker/                Prefect worker entrypoint + health server
│   │       ├── observability/
│   │       └── cli.py                 `ecolens-pipeline` console script
│   │
│   └── dashboard/                     ③ SERVICE 3 / 3   — Next.js 15 + TS
│       ├── package.json
│       ├── tsconfig.json
│       ├── next.config.ts
│       ├── tailwind.config.ts
│       ├── public/
│       ├── tests/                     Vitest + Playwright
│       └── app/                       App Router
│           ├── page.tsx               marketing
│           ├── dashboard/
│           ├── forecast/
│           ├── emissions/
│           ├── footprint/
│           └── api/                   BFF routes (proxies to forecast-api)
│
├── data/                              ← gitignored; volume-mounted in dev
│   ├── raw/
│   ├── processed/
│   ├── external/
│   └── schemas/                       JSON schemas for raw payloads
│
├── infra/                             ← ops
│   ├── docker/                        one Dockerfile per service
│   │   ├── forecast-api.Dockerfile
│   │   ├── data-pipeline.Dockerfile
│   │   ├── dashboard.Dockerfile
│   │   └── mlflow.Dockerfile
│   ├── prometheus/
│   ├── grafana/dashboards/
│   └── k8s/                           per-service Helm charts (one per service)
│       ├── forecast-api/
│       ├── data-pipeline/
│       └── dashboard/
│
├── scripts/                           ← dev / ops scripts
│   ├── seed.sh
│   ├── promote_model.sh
│   └── deploy.sh
│
├── docs/                              ← cross-service docs
│   ├── architecture.md
│   ├── data-sources.md
│   ├── model-card.md
│   ├── api-reference.md
│   ├── deployment.md
│   ├── microservices-action-plan.md   ← the 3-service plan & rationale
│   ├── runbooks/                      one per service
│   └── adr/                           Architecture Decision Records
│
├── notebooks/                         exploratory work (shared)
│   ├── 01_eda.ipynb
│   ├── 02_baseline.ipynb
│   └── 03_lstm_experiments.ipynb
│
└── .github/
    ├── workflows/
    │   ├── ci.yml                     path-filtered, one job per service
    │   ├── ml-pipeline.yml            dbt build + model train (scheduled)
    │   ├── docker.yml                 build & push per-service image
    │   ├── codeql.yml
    │   └── release.yml                signed release
    ├── PULL_REQUEST_TEMPLATE.md
    └── ISSUE_TEMPLATE/
```

---

## ⚡ Quickstart

> Requires **python 3.12+**, **Node 20+**, **Docker 24+**, **uv**, **pnpm**.

### 1. Clone & configure

```bash
git clone https://github.com/diptu/ecoLens.git
cd ecoLens
cp .env.example .env
# Edit .env — at minimum: OPENELECTRICITY_API_KEY
```

### 2. Bring up all 3 services + infra

```bash
make up
```

One command starts **`forecast-api` (port 8000)**, **`data-pipeline`
(headless worker)**, and **`dashboard` (port 3000)** — plus the platform
infra (postgres, redis, minio, mlflow, prometheus, grafana, loki).

```text
  forecast-api  → http://localhost:8000    (OpenAPI: /docs)
  data-pipeline → running headless          (logs: make logs-pipeline)
  dashboard     → http://localhost:3000
  mlflow        → http://localhost:5000
  grafana       → http://localhost:3001     (admin / admin)
```

### 3. Build the warehouse (dbt)

```bash
make dbt-build          # seeds + run + test
```

Runs **inside** the `data-pipeline` container, so it uses the same image
that will be deployed.

### 4. Train the demand model

```bash
make train MODEL=lstm_demand REGION=NEM
# Or full Optuna sweep:
make tune MODEL=lstm_demand REGION=NEM TRIALS=50
```

The run is tracked in MLflow at <http://localhost:5000>. When the model is
promoted to `Production`, `forecast-api` hot-reloads it on the next request
— **no service-to-service call**, just a watch on the MLflow registry.

### 5. Use the app

```bash
# Open the UI
open http://localhost:3000

# Or hit the API directly
curl http://localhost:8000/v1/healthz
curl 'http://localhost:8000/v1/forecast?region=NSW1&horizon=24h'
curl -X POST http://localhost:8000/v1/footprint \
  -H 'content-type: application/json' \
  -d '{"region":"NSW1","kwh":420,"period":"2026-07-01T00:00Z/2026-07-31T23:59Z"}'
```

### 6. Work on a single service

```bash
# Tail logs for one service
make logs-api
make logs-pipeline
make logs-dashboard

# Open a shell
make shell-api
make shell-pipeline
make shell-dashboard

# Restart just one
make restart-api

# Run a service without Docker (faster inner loop)
make api                # forecast-api in foreground
make pipeline           # data-pipeline worker
make web                # dashboard dev server
```

### 7. Tear down

```bash
make down
```

---

## 🧠 ML pipeline

> **Owner:** the `data-pipeline` service. All ingestion, dbt, training and
> MLflow registration runs there. The `forecast-api` service only **loads**
> the registered model — it never trains. See
> [`docs/microservices-action-plan.md`](docs/microservices-action-plan.md) for
> the service-boundary rationale.

### Demand forecasting (PyTorch LSTM)

The model is a **multivariate, multi-horizon LSTM**:

- **Inputs** (per 30-min step): regional demand, price, temperature, humidity,
  solar irradiance, hour-of-day, day-of-week, public-holiday flag, lagged demand
  at 1d/7d/28d, rolling mean at 24h/168h.
- **Architecture**: 2-layer `nn.LSTM` (hidden=128, dropout=0.2) →
  attention pooling → fully-connected head producing 48-step outputs.
- **Loss**: Huber (robust to dispatch spikes), with a separate pinball loss
  branch for 10/90 quantile heads.
- **Trainer**: PyTorch Lightning, mixed-precision, gradient clipping,
  ReduceLROnPlateau, early stopping on val MAPE.
- **Uncertainty**: Conformal prediction over the calibration set, returned as
  P10/P50/P90 bands.
- **Tracking**: every run → MLflow (params, metrics, git SHA, model signature,
  artifact store on MinIO/S3).

See [`docs/model-card.md`](docs/model-card.md) for the full model card
(performance, intended use, limitations, ethics).

### Feature engineering (dbt)

We don't compute features in pandas and then lose them. Features live as
**dbt models** in `dbt/ecolens/models/intermediate/`:

```sql
-- models/intermediate/int_demand_with_weather.sql
with demand as (
  select * from {{ ref('stg_aemo_nem_dispatch') }}
),
weather as (
  select * from {{ ref('stg_bom_observations') }}
)
select
  d.ts,
  d.region,
  d.demand_mw,
  w.temp_c,
  w.radiation_mj_m2,
  extract(hour    from d.ts) as hour,
  extract(dow     from d.ts) as dow,
  lag(d.demand_mw, 48)  over (partition by d.region order by d.ts) as lag_1d,
  lag(d.demand_mw, 336) over (partition by d.region order by d.ts) as lag_7d,
  avg(d.demand_mw) over (
    partition by d.region order by d.ts rows between 335 preceding and current row
  ) as roll_7d
from demand d
left join weather w
  on d.region = w.region and d.ts = w.ts
```

The training set is **materialised as a Parquet snapshot** in S3 per training
run — the model never trains on a live Postgres connection.

### MLflow

- Tracking server: `mlflow server --backend-store-uri postgresql://... --default-artifact-root s3://ecolens/mlflow`
- Model registry stages: `None → Staging → Production → Archived`.
- Promotion is **CI-gated** — see
  [`scripts/promote_model.sh`](scripts/promote_model.sh) and the
  `ml-pipeline` GitHub Action.

### Orchestration (Prefect)

```python
# services/data-pipeline/src/ecolens/pipeline/flows.py
@flow(name="daily-demand")
def daily_demand():
    raw    = ingest_aemo_nem()          # land in S3
    load   = load_raw_to_postgres(raw)  # → raw schema
    dbt_build(target="prod")            # → analytics schema
    if training_due():
        train_and_register("lstm_demand", region="NEM")
```

Schedules: ingest every 5 min (NEM), 30 min (WEM), dbt every 15 min,
retrain weekly, daily evaluation drift report.

---

## 🌐 API reference

Base URL: `https://api.ecolens.example/v1` · OpenAPI: `/docs` · ReDoc: `/redoc`

| Method | Path | Description |
| --- | --- | --- |
| `GET`  | `/healthz` | Liveness — 200 if the process is up |
| `GET`  | `/readyz`  | Readiness — checks DB, Redis, model load |
| `GET`  | `/v1/forecast` | Demand forecast, point + intervals |
| `GET`  | `/v1/emissions` | Live emissions for a region |
| `POST` | `/v1/footprint` | Compute kgCO₂e for user kWh |
| `GET`  | `/v1/regions` | List supported regions |
| `GET`  | `/v1/model` | Currently-served model metadata (MLflow) |
| `WS`   | `/v1/stream/emissions` | Server-sent stream, 5-min updates |

### `GET /v1/forecast`

```http
GET /v1/forecast?region=NSW1&horizon=24h&interval=30m HTTP/1.1
```

```json
{
  "region": "NSW1",
  "model": "lstm_demand@production",
  "generated_at": "2026-07-18T09:00:00Z",
  "horizon": "24h",
  "interval": "30m",
  "points": [
    { "ts": "2026-07-18T09:00:00Z", "p10": 8120, "p50": 8940, "p90": 9810, "unit": "MW" }
  ]
}
```

### `POST /v1/footprint`

```http
POST /v1/footprint HTTP/1.1
content-type: application/json

{ "region": "NSW1", "kwh": 420, "period": "2026-07-01T00:00Z/2026-07-31T23:59Z" }
```

```json
{
  "region": "NSW1",
  "kwh": 420,
  "kg_co2e": 187.4,
  "intensity_kg_co2e_per_kwh": 0.446,
  "method": "live_mix_weighted",
  "factors_version": "nger-2025-q4"
}
```

Schemas live in `src/ecolens/api/schemas/` and are exported as JSON Schema in
the OpenAPI doc. All endpoints are rate-limited (Redis token bucket,
default 60 req/min per token).

---

## 🖥️ Frontend

The web app is a **Next.js 15 App Router** project (`/frontend`):

- **Server Components** for first paint; **TanStack Query** for live data
  with stale-while-revalidate.
- **Recharts** for time-series, **react-map-gl** for the regional map.
- **shadcn/ui + Tailwind 4** for accessible primitives.
- **Auth.js** with OIDC; carbon footprint calculator requires a free account.
- **PWA-ready** (offline dashboard for the last 24h of cached emissions).
- **Playwright** e2e covering the three critical user journeys:
  forecast, footprint, share.

Pages:

| Route | What |
| --- | --- |
| `/` | Marketing + live grid snapshot |
| `/dashboard` | Live demand vs forecast, generation mix, intensity |
| `/forecast` | Forecast explorer with horizon, region, confidence bands |
| `/emissions` | Historical emissions explorer (5-min granularity) |
| `/footprint` | Personal/business Scope-2 calculator |
| `/about` | Methodology, sources, model card |

---

## 🧮 Emissions model

For any `(region, interval)`:

```
emissions_kgco2e =
    Σ_fuel  generation_mwh[fuel] × intensity_kgco2e_per_mwh[fuel]
```

where `intensity` is sourced from AEMO/NGER and stored in
`dbt/ecolens/seeds/emissions_factors.csv` (versioned; see the
`factors_version` field in API responses). For a user-supplied kWh over a
period, the platform:

1. Resolves the **energy mix** for that region during the period
   (live mix, or historical from the warehouse).
2. Computes the **time-weighted average intensity** (kgCO₂e/kWh).
3. Returns `kwh × intensity` and the breakdown.

OpenElectricity already publishes emission factors, but we **don't blindly
trust the third-party number** — our calculator lets you choose between:

- `live_mix_weighted` — our calculation, real-time
- `live_provider` — what OpenElectricity reports for the same window
- `static_nger` — audit-grade, NGER factors only

This is the **triangulation** that makes the number defensible.

See [`docs/emissions-model.md`](docs/emissions-model.md) (TODO) for the
full formula and unit tests.

---

## 📈 Observability

| Signal | Backend | Where |
| --- | --- | --- |
| Traces | OpenTelemetry → Tempo / Jaeger | Auto-instrumented FastAPI, dbt, PyTorch |
| Metrics | Prometheus | `/metrics` on the API; Prefect + MLflow exporters |
| Logs | Loki via Vector | JSON logs, `trace_id` correlation |
| Errors | Sentry | Frontend + backend |
| Dashboards | Grafana | `infra/grafana/dashboards/{api,ml,grid}.json` |
| Alerts | Alertmanager | Page on SLO burn, drift, ingest lag |

**SLOs** (initial):

- `/v1/forecast` 95p latency < 250 ms (cache hit), < 1.2 s (cold)
- `/v1/footprint` 95p latency < 400 ms
- Forecast MAPE < 6% on rolling 28-day window
- 99.5% monthly availability for the API

---

## 🧪 Testing

```bash
make test            # all tests
make test-unit       # fast, no IO
make test-int        # spins up testcontainers
make test-e2e        # Playwright + httpx
make test-ml         # data + model regression tests (deterministic)
```

Quality gates in CI:

- `ruff check` + `ruff format --check`
- `mypy --strict` on `src/`
- `pytest -q` with coverage gate (≥ 85% on `src/ecolens/`)
- `bandit -r src/`
- `trivy fs .` and `trivy image`
- `dbt build` (must pass)
- `gitleaks` for secrets

---

## 🚀 Deployment

### 3 services, 3 images

Each service has its own **multi-stage, distroless, non-root, cosign-signed**
Dockerfile, its own image tag, and its own deploy lane:

| Service | Dockerfile | Image | Default port |
|---|---|---|---|
| `forecast-api`  | `infra/docker/forecast-api.Dockerfile`  | `ghcr.io/diptu/ecoLens/forecast-api`  | `8000` |
| `data-pipeline` | `infra/docker/data-pipeline.Dockerfile` | `ghcr.io/diptu/ecoLens/data-pipeline` | — (headless) |
| `dashboard`     | `infra/docker/dashboard.Dockerfile`     | `ghcr.io/diptu/ecoLens/dashboard`     | `3000` |

Image tags follow `v<semver>`, `<sha>`, and `latest` for `main`.

### Local stack (development)

```bash
make up
# = docker compose -f docker-compose.yml up -d
```

This brings up the **3 application services + 7 platform-infra
dependencies** (postgres, redis, minio, mlflow, prometheus, grafana, loki).
Use `make down`, `make logs`, and `make ps` to manage it.

### Production

Two supported targets:

1. **Container service** (Render / Fly / Railway / ECS / Cloud Run) —
   the easiest path. Deploy each of the 3 services as its own service,
   point them at the same Postgres / Redis / S3 / MLflow. See
   [`docs/deployment.md`](docs/deployment.md) for env-by-env specifics.
2. **Kubernetes** — per-service Helm chart under `infra/k8s/{forecast-api,
   data-pipeline, dashboard}/` (Argo CD-managed). HPA on CPU for the API
   and dashboard; HPA on a custom `forecast_qps` metric for the API; the
   data-pipeline runs as a `Deployment` with a fixed replica count and a
   Prefect worker pool.

### CI/CD

CI is **path-filtered per service** so changes to `services/dashboard/**`
don't rebuild the API image.

| Workflow | Trigger | What |
| --- | --- | --- |
| `ci.yml`           | PR, push               | Lint + type + test per service; build 3 images in parallel |
| `ml-pipeline.yml`  | Daily cron, manual     | dbt build → train → evaluate → register in MLflow |
| `docker.yml`       | Tag `v*`               | Build, sign (`cosign`), push the 3 service images |
| `release.yml`      | Tag `v*`               | SBOM (CycloneDX) + SLSA provenance + GitHub release |
| `codeql.yml`       | PR, push               | CodeQL scan across the 3 services |

### Model promotion

A model is **only** promoted to `Production` when:

1. All CI checks pass on the candidate.
2. Rolling-28d MAPE is **strictly better** than the current production model
   on the same evaluation set.
3. A human approves via PR (or, in fully-automated mode, the
   `model-promoter` policy in `ml-pipeline.yml`).

Once promoted, `forecast-api` picks it up by watching the MLflow registry —
no rolling restart, no service-to-service call.

---

## 🔐 Security

- Non-root containers, distroless base, read-only filesystems.
- All secrets via env + secret manager (never committed).
- `gitleaks` on pre-commit + CI.
- `bandit` + `codeql` static analysis.
- `trivy` scans on every PR and every image.
- OpenSSF Scorecard target: **7+**.
- SBOM (CycloneDX) + SLSA provenance on every release.
- Rate limiting, request size limits, CORS allowlist, CSP, HSTS.
- Dependency review bot blocks new vulns.
- `SECURITY.md` with coordinated disclosure — see file.

---

## 🗺️ Roadmap

- [x] Repo scaffold + dbt + FastAPI skeleton
- [ ] Baseline LSTM v0 (NSW1) — univariate, no weather
- [ ] Multivariate LSTM v1 — weather + calendar features
- [ ] Conformal prediction intervals
- [ ] WEM (SWIS) training pipeline
- [ ] OpenElectricity live ingest → Redis stream
- [ ] Footprint calculator UI + shareable link
- [ ] Drift monitoring (Evidently) + auto-retrain policy
- [ ] Multi-region transformer baseline
- [ ] Greenhouse gas protocol Scope-3 add-on
- [ ] Mobile (React Native, Expo)
- [ ] Public API + developer tier

See [`docs/roadmap.md`](docs/roadmap.md) for the living plan.

---

## 🤝 Contributing

We welcome issues, PRs, and data contributions. Please read
[`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
before opening a PR.

TL;DR:

1. Fork → branch from `main`.
2. `make bootstrap` then `make dev`.
3. PR with a description, linked issue, and a screenshot if UI.
4. CI must be green; one approval from a CODEOWNER required.

Feature flags go in `src/ecolens/config.py`; breaking changes need an
[ADR](docs/adr/) entry.

---

## 📄 License & attribution

**Code:** [MIT](LICENSE) © 2024–2026 ecoLens contributors.

**Data attribution** (mandatory when redistributing derived numbers):

- AEMO — Australian Energy Market Operator. Data is provided subject to
  AEMO's copyright and disclaimer.
- OpenElectricity (formerly OpenNEM) — © OpenElectricity contributors,
  licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
  Commercial use requires a [licence from OpenElectricity](https://platform.openelectricity.org.au/).
- Bureau of Meteorology — © Commonwealth of Australia, licensed under
  [CC BY 3.0 AU](https://creativecommons.org/licenses/by/3.0/au/).
- DCCEEW NGER — © Commonwealth of Australia, CC BY 4.0.
- Electricity Maps AU-WA — © Electricity Maps, ODbL.

ecoLens is an independent project and is **not affiliated with, endorsed by,
or sponsored by AEMO, OpenElectricity, the BOM, or the Australian
Government**. Trademarks belong to their respective owners.

---

## 📚 Citation

If you use ecoLens in research, please cite:

```bibtex
@software{ecolens_2026,
  title  = {ecoLens: Real-time electricity demand forecasting and
            carbon-footprint intelligence for the Australian NEM},
  author = {ecoLens contributors},
  year   = {2026},
  url    = {https://github.com/diptu/ecoLens},
  note   = {Data: AEMO, OpenElectricity, BoM, DCCEEW}
}
```

---

## 👥 Maintainers

- **@diptu** — original author
- See [`CODEOWNERS`](CODEOWNERS) for the full roster

Questions? Open an issue or start a discussion.
**Built with care for a lower-carbon grid.** 🌱

</div>
