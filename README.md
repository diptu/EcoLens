<div align="center">

# 🌱 ecoLens

### Near-real-time electricity demand forecasting & carbon-footprint intelligence for the Australian energy grid.

**Event-driven · Probabilistic Forecasting · Carbon Intelligence · MLOps · Observability**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![Next.js 15](https://img.shields.io/badge/Frontend-Next.js%2015-black.svg)](https://nextjs.org)
[![PyTorch 2.x](https://img.shields.io/badge/ML-PyTorch%202.x-ee4c2c.svg)](https://pytorch.org)
[![MLflow](https://img.shields.io/badge/MLOps-MLflow-0194E2.svg)](https://mlflow.org)
[![dbt](https://img.shields.io/badge/Transform-dbt-FF694B.svg)](https://www.getdbt.com)
[![PostgreSQL](https://img.shields.io/badge/Warehouse-PostgreSQL%2016-336791.svg)](https://www.postgresql.org)
[![DuckDB](https://img.shields.io/badge/Staging-DuckDB-FFF000.svg)](https://duckdb.org)
[![RabbitMQ](https://img.shields.io/badge/Events-RabbitMQ-FF6600.svg)](https://www.rabbitmq.com)
[![Redis 7](https://img.shields.io/badge/Cache-Redis%207-DC382D.svg)](https://redis.io)
[![OpenTelemetry](https://img.shields.io/badge/Observability-OpenTelemetry-000000.svg)](https://opentelemetry.io)

**ecoLens** is an end-to-end energy intelligence platform that transforms near-real-time
electricity-system data into demand forecasts, generation-mix predictions, carbon
intelligence, and actionable operational insights.

The platform combines event-driven data engineering, probabilistic time-series
forecasting, adaptive machine learning, carbon accounting, MLOps, and centralized
observability into a decoupled microservice architecture.

[Overview](#-overview) ·
[Architecture](#-architecture) ·
[Data Pipeline](#-data-pipeline) ·
[ML Pipeline](#-ml--forecasting) ·
[Carbon Intelligence](#-carbon-intelligence) ·
[Observability](#-observability) ·
[Quickstart](#-quickstart)

</div>

---

## 📑 Table of Contents

1. [Overview](#-overview)
2. [What ecoLens Answers](#-what-ecolens-answers)
3. [Key Capabilities](#-key-capabilities)
4. [Architecture](#-architecture)
5. [Microservices](#-microservices)
6. [Data Pipeline](#-data-pipeline)
7. [Event-Driven Warehousing](#-event-driven-warehousing)
8. [Storage Architecture](#-storage-architecture)
9. [ML & Forecasting](#-ml--forecasting)
10. [Probabilistic Forecasting](#-probabilistic-forecasting)
11. [Adaptive Learning](#-adaptive-learning)
12. [Anomaly Detection](#-anomaly-detection)
13. [Model Optimization](#-model-optimization)
14. [Carbon Intelligence](#-carbon-intelligence)
15. [MLOps & Model Lifecycle](#-mlops--model-lifecycle)
16. [Observability](#-observability)
17. [Frontend](#-frontend)
18. [Data Sources](#-data-sources)
19. [Technology Stack](#-technology-stack)
20. [Repository Structure](#-repository-structure)
21. [Quickstart](#-quickstart)
22. [API](#-api)
23. [Testing & Quality](#-testing--quality)
24. [Security](#-security)
25. [Deployment](#-deployment)
26. [Roadmap](#-roadmap)
27. [Contributing](#-contributing)
28. [License & Attribution](#-license--attribution)

---

# 🌍 Overview

**ecoLens** is an end-to-end electricity demand forecasting and carbon-footprint
intelligence platform designed around the Australian electricity market.

It bridges operational energy data and environmental intelligence by combining:

* Near-real-time electricity-system data ingestion
* Automated anomaly detection
* Event-driven data warehousing
* Historical and real-time energy analytics
* Probabilistic electricity demand forecasting
* Generation-mix forecasting
* Adaptive and incremental machine learning
* Carbon intensity estimation
* Future emissions estimation
* Model lifecycle management
* Centralized observability
* Interactive energy and sustainability dashboards

The platform is designed to answer two fundamental questions:

> **How much electricity will be needed over the next 24 hours?**

and

> **How clean will that electricity be based on the expected generation mix?**

Rather than treating forecasting and carbon accounting as separate problems,
ecoLens connects them into a single analytical pipeline.

```text
External Energy Data
        │
        ▼
┌───────────────────┐
│    Ingestion      │
│ AEMO / BoM / OE   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Anomaly Detection │
│ Rules + ML Models │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ DuckDB Staging    │
└─────────┬─────────┘
          │
       RabbitMQ
          │
          ▼
┌───────────────────┐
│ PostgreSQL Raw    │
│   raw.* schema    │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│       dbt         │
│ Transformations   │
└─────────┬─────────┘
          │
          ▼
┌────────────────────────────┐
│ Curated Analytical Marts   │
└────────────┬───────────────┘
             │
       ┌─────┴──────┐
       ▼            ▼
 Forecasting    Carbon Engine
       │            │
       └─────┬──────┘
             ▼
       FastAPI Services
             │
             ▼
       Next.js Dashboard
```

---

# ❓ What ecoLens Answers

### 1. Future electricity demand

The forecasting system estimates electricity demand over future horizons using
historical demand, weather, calendar, market, and generation features.

Forecasts are represented probabilistically rather than as a single deterministic
number.

```text
P10 ───── Conservative / lower-demand scenario
P50 ───── Expected demand
P90 ───── High-demand scenario
```

### 2. Future generation composition

The platform analyses and forecasts the contribution of different generation
sources such as:

* Coal
* Gas
* Wind
* Solar
* Hydro
* Batteries
* Other generation

### 3. Future carbon impact

Demand forecasts are combined with generation-mix and emissions-intensity
information to estimate:

* Carbon intensity
* Renewable contribution
* Expected emissions
* Carbon footprint
* Historical vs forecast environmental impact

---

# ✨ Key Capabilities

## ⚡ Energy Data Intelligence

* AEMO NEM data ingestion
* AEMO WEM data ingestion
* OpenElectricity generation-mix data
* BoM weather data
* Multi-frequency ingestion
* Historical backfilling
* Near-real-time updates

## 🔍 Data Quality & Anomaly Detection

Hybrid anomaly detection combines:

* Rule-based validation
* Statistical checks
* Machine-learning anomaly detection
* Anomaly scoring
* Human-readable explanations

Anomalous observations are **flagged rather than automatically deleted**.

This preserves genuine operational events while allowing downstream systems to
distinguish between data-quality problems and real grid events.

---

## 🔮 Probabilistic Forecasting

The forecasting system produces:

* P10
* P50
* P90

instead of a single point estimate.

This allows downstream applications to reason about uncertainty and plan for
different demand scenarios.

---

## 🧠 Adaptive Machine Learning

ecoLens supports an adaptive forecasting architecture using specialized models
such as:

* PyTorch LSTM
* Temporal Fusion Transformer (TFT)
* TimesFM

Models can incorporate newly observed data through online/incremental learning
workflows to adapt to:

* Changing demand patterns
* Seasonal behaviour
* Weather changes
* Renewable penetration
* Market changes
* Concept drift

---

## 🛡️ Conformal Uncertainty Calibration

Forecast uncertainty is continuously monitored through conformal calibration.

The platform tracks whether the prediction intervals maintain their expected
coverage.

For example:

```text
Target coverage: 80%

Observed coverage
        │
        ├── Healthy → continue
        │
        ├── Degrading → recalibrate
        │
        └── Severe → trigger model fallback/retraining workflow
```

This separates **forecast accuracy** from **forecast uncertainty quality**.

---

## ✂️ Model Optimization

To reduce inference cost and latency, ecoLens supports structured model pruning.

The optimization workflow is:

```text
Full Model
    │
    ▼
Importance Analysis
    │
    ▼
Structured Pruning
    │
    ▼
Smaller Model
    │
    ▼
Fine-Tuning
    │
    ▼
Validation
    │
    ▼
Production Candidate
```

The objective is to reduce unnecessary model complexity while preserving
forecasting performance.

---

# 🏗️ Architecture

ecoLens follows a **decoupled, event-driven microservice architecture**.

```text
                              ┌─────────────────────┐
                              │       USERS         │
                              └──────────┬──────────┘
                                         │ HTTPS
                                         ▼
                              ┌─────────────────────┐
                              │      Dashboard      │
                              │      Next.js 15     │
                              └──────────┬──────────┘
                                         │ REST
                                         ▼
                              ┌─────────────────────┐
                              │    Forecast API     │
                              │      FastAPI        │
                              └──────┬───────┬──────┘
                                     │       │
                                     ▼       ▼
                                  Redis   PostgreSQL
                                  Cache     Marts
                                     ▲
                                     │
═════════════════════════════════════╪══════════════════════════════
                                     │
                          Event / Data Boundary
                                     │
                                     ▼
                              ┌──────────────────┐
                              │   Data Pipeline  │
                              │                  │
                              │ Celery/Prefect   │
                              │ Ingestion        │
                              │ Anomaly Detection│
                              │ DuckDB           │
                              │ dbt              │
                              │ Training         │
                              └────────┬─────────┘
                                       │
                                       │ Event
                                       ▼
                                  RabbitMQ
                                       │
                                       ▼
                              PostgreSQL raw.*
                                       │
                                       ▼
                                   dbt marts
                                       │
                                       ▼
                              Forecasting / Carbon
```

### Observability is intentionally outside the business-data path

```text
          ┌───────────────────┐
          │  Ingestion        │────┐
          └───────────────────┘    │
                                   │
          ┌───────────────────┐    │
          │  Warehouse        │────┼──► OpenTelemetry
          └───────────────────┘    │
                                   │
          ┌───────────────────┐    │
          │  Forecast         │────┘
          └───────────────────┘
                    │
                    ▼
          ┌────────────────────┐
          │ OTel Collector     │
          └──────┬─────┬───────┘
                 │     │
          ┌──────▼┐ ┌──▼────┐ ┌────────┐
          │Prom.  │ │ Loki  │ │ Tempo  │
          └───┬───┘ └──┬────┘ └───┬────┘
              └────────┼───────────┘
                       ▼
                   Grafana
```

Telemetry is asynchronous or scrape-based and does not become a dependency in
the critical business-data execution path.

---

# 🧩 Microservices

ecoLens is organized around independently deployable services.

| Service           | Responsibility                                                         | Communication           |
| ----------------- | ---------------------------------------------------------------------- | ----------------------- |
| **Ingestion**     | External API collection, validation, anomaly detection, DuckDB staging | RabbitMQ                |
| **Warehouse**     | Raw landing, dbt transformations, analytical datasets                  | RabbitMQ + PostgreSQL   |
| **Forecast**      | Model serving, forecasting, carbon intelligence, API                   | REST + Redis/PostgreSQL |
| **Dashboard**     | Visualization and user experience                                      | REST                    |
| **Observability** | Telemetry collection and monitoring                                    | OpenTelemetry           |

Each business service can be developed, tested, deployed, and scaled independently.

---

# 📥 Data Pipeline

The ingestion system operates according to the source's required polling
frequency.

```text
Scheduler
   │
   ├── 5-minute sources
   │
   └── 30-minute sources
          │
          ▼
      Celery Tasks
          │
          ▼
     External APIs
          │
          ▼
   Validation / Normalization
          │
          ▼
   Hybrid Anomaly Detection
          │
          ▼
       DuckDB
          │
          ▼
   "data.staged" event
          │
          ▼
      RabbitMQ
```

The ingestion service does not wait for the warehouse to finish processing.
This keeps data collection resilient to downstream processing delays.

---

# 🔍 Anomaly Detection

Each ingested record can be evaluated using a hybrid anomaly-detection layer.

```text
                    Incoming Record
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
       Rule-based checks          ML detection
              │                         │
              └────────────┬────────────┘
                           ▼
                    Anomaly Score
                           │
                    Explanation
                           │
                           ▼
                    Store + Flag
```

Examples include:

* Missing values
* Invalid ranges
* Unexpected frequency
* Sudden demand changes
* Generation spikes
* API response anomalies
* Sensor-like failures

The system intentionally avoids blindly removing anomalous observations because
a large deviation may represent a genuine grid event.

---

# 📨 Event-Driven Warehousing

After staging data in DuckDB, the ingestion service publishes a completion event
through RabbitMQ.

```text
DuckDB
   │
   │ data.staged
   ▼
RabbitMQ
   │
   ▼
Warehouse Consumer
   │
   ▼
PostgreSQL raw.*
   │
   ▼
dbt
   │
   ├── staging
   ├── intermediate
   └── marts
```

This creates a clear boundary between:

**Data collection**

and

**Data processing**

The warehouse therefore does not need to poll the ingestion service repeatedly,
and ingestion does not need to wait for warehouse processing.

---

# 🗄️ Storage Architecture

ecoLens uses a layered storage strategy.

| Layer        | Technology                         | Purpose                                    |
| ------------ | ---------------------------------- | ------------------------------------------ |
| Staging      | **DuckDB**                         | Local high-performance ingestion staging   |
| Raw          | **PostgreSQL**                     | Immutable historical source representation |
| Curated      | **PostgreSQL + dbt**               | Analytics-ready datasets                   |
| Artifacts    | **Cloudflare R2 / object storage** | Durable artifacts and files                |
| Cache        | **Redis**                          | Low-latency serving                        |
| ML artifacts | **MLflow + object storage**        | Models, metrics, training artifacts        |

### Raw layer

The `raw.*` schema stores data as close as possible to the original source
representation.

This provides:

* Auditability
* Reprocessing
* Data lineage
* Debugging
* Historical reconstruction

### Curated layer

dbt transforms raw data into analytics-ready datasets used by:

* Forecasting
* Carbon accounting
* Dashboards
* Reporting
* Monitoring

---

# 🧠 ML & Forecasting

The forecasting system is designed as a multi-model architecture.

```text
                 Curated Energy Data
                         │
                         ▼
                 Feature Engineering
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
         LSTM            TFT          TimesFM
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                 Forecast Ensemble
                         │
                         ▼
              Probabilistic Output
                 P10 / P50 / P90
```

### Input features

Potential forecasting features include:

* Historical demand
* Lagged demand
* Rolling statistics
* Weather
* Temperature
* Solar radiation
* Calendar features
* Time-of-day
* Day-of-week
* Holidays
* Electricity price
* Generation mix
* Renewable penetration

---

# 📊 Probabilistic Forecasting

Instead of returning:

```text
Demand = 8,420 MW
```

ecoLens produces:

```text
P10 = 7,900 MW
P50 = 8,420 MW
P90 = 9,150 MW
```

This provides decision-makers with a range of plausible future outcomes.

The forecasting layer monitors both:

### Point accuracy

* MAE
* RMSE
* MAPE / sMAPE where appropriate

### Probabilistic quality

* Prediction interval coverage
* Calibration
* Interval width
* Quantile loss

---

# 🔄 Adaptive Learning

Electricity demand is non-stationary.

Patterns change because of:

* Weather
* Consumer behaviour
* Renewable generation
* Market conditions
* Grid infrastructure
* Seasonal changes
* Exceptional events

ecoLens therefore supports online and incremental learning workflows.

```text
New Observations
       │
       ▼
Feature Update
       │
       ▼
Drift Detection
       │
       ├── Stable ──────────► Continue
       │
       ├── Moderate Drift ──► Incremental Update
       │
       └── Severe Drift ────► Retraining
                                  │
                                  ▼
                            Model Validation
                                  │
                                  ▼
                            Model Registry
                                  │
                                  ▼
                            Production
```

---

# 🛡️ Model Reliability

Forecast reliability is monitored continuously.

The platform tracks:

* Rolling forecasting error
* Prediction interval coverage
* Feature drift
* Concept drift
* Model degradation
* Calibration degradation

Potential actions include:

```text
Healthy
   │
   ▼
Continue serving

Degraded calibration
   │
   ▼
Recalibrate uncertainty

Performance degradation
   │
   ▼
Incremental learning

Severe degradation
   │
   ▼
Retrain / promote validated model
```

A validated baseline model can be retained as a fallback when the primary model
fails production health checks.

---

# ✂️ Model Optimization

ecoLens supports structured pruning for reducing model complexity.

The optimization objective is:

```text
Lower computational cost
        +
Lower inference latency
        +
Smaller model
        +
Minimal accuracy degradation
```

The workflow includes:

1. Train baseline
2. Measure feature/layer importance
3. Apply structured pruning
4. Fine-tune
5. Evaluate
6. Compare against baseline
7. Register optimized model
8. Deploy only after validation

---

# 🌱 Carbon Intelligence

Demand forecasting alone does not describe environmental impact.

ecoLens combines:

```text
Forecast Electricity Demand
             +
Expected Generation Mix
             +
Fuel-specific Emission Factors
             │
             ▼
      Carbon Intensity
             │
             ▼
      Expected Emissions
```

The system can derive or consume:

* Carbon intensity
* Renewable proportion
* Generation mix
* Fuel-specific emission factors
* Expected emissions
* Historical emissions

When direct renewable-energy metrics are unavailable, renewable contribution can
be estimated from the observed generation mix.

---

# 🧮 Carbon Footprint

For a given electricity consumption:

```text
Carbon Footprint

= Electricity Consumption
  × Carbon Intensity
```

For example:

```text
kWh × kgCO₂e/kWh = kgCO₂e
```

The calculation can use:

* Current regional intensity
* Historical intensity
* Forecast intensity

depending on the analytical use case.

---

# 🧪 MLOps & Model Lifecycle

MLflow provides centralized experiment and model lifecycle management.

```text
Training Data
     │
     ▼
Experiment
     │
     ├── Parameters
     ├── Metrics
     ├── Dataset metadata
     └── Artifacts
            │
            ▼
        MLflow
            │
            ▼
      Model Validation
            │
            ▼
       Model Registry
            │
            ▼
       Production Model
```

Tracked information includes:

* Model version
* Training dataset
* Hyperparameters
* Evaluation metrics
* Forecasting metrics
* Calibration metrics
* Model artifacts
* Training metadata

This enables reproducible experimentation and controlled production deployment.

---

# 📡 Observability

ecoLens uses a dedicated observability architecture so that monitoring does not
couple the business services together.

Each service produces:

* Metrics
* Structured logs
* Distributed traces

through OpenTelemetry.

```text
┌─────────────┐
│ Ingestion   │──┐
└─────────────┘  │
                 │
┌─────────────┐  │
│ Warehouse   │──┼──► OpenTelemetry Collector
└─────────────┘  │             │
                 │       ┌─────┼─────┐
┌─────────────┐  │       ▼     ▼     ▼
│ Forecast    │──┘    Prom.  Loki  Tempo
└─────────────┘              │
                             ▼
                          Grafana
```

### System observability

The platform monitors:

* Service availability
* Request latency
* Error rates
* CPU / memory usage
* Queue health
* Pipeline execution
* Ingestion failures
* Warehouse processing latency
* API performance

### ML observability

The platform also monitors:

* MAE
* RMSE
* Forecast bias
* P10/P90 coverage
* Feature drift
* Concept drift
* Calibration
* Model degradation
* Retraining indicators

This creates a direct connection between **data quality → model performance →
model lifecycle decisions**.

### Non-blocking telemetry

Observability is not part of the business-critical execution path.

If the observability stack becomes unavailable, the core ingestion, warehouse,
and forecasting workflows should continue operating.

---

# 🖥️ Frontend

The frontend is built with **Next.js 15** and provides an interactive interface for:

* Real-time grid conditions
* Electricity demand
* Demand forecasts
* P10/P50/P90 uncertainty bands
* Generation mix
* Renewable contribution
* Carbon intensity
* Historical emissions
* Forecast emissions
* Model performance
* Data quality
* System health

The frontend communicates with backend services through REST APIs rather than
accessing databases directly.

```text
Next.js
   │
   │ REST
   ▼
Forecast API
   │
   ├── Redis
   └── PostgreSQL
```

This preserves a clean boundary between presentation and data infrastructure.

---

# 📚 Data Sources

| Source               | Data                                 |        Frequency |
| -------------------- | ------------------------------------ | ---------------: |
| **AEMO NEM**         | Demand, generation, prices           |            5 min |
| **AEMO WEM**         | SWIS demand/generation               |           30 min |
| **OpenElectricity**  | Generation mix / emissions           |   Near-real-time |
| **BoM**              | Weather observations                 | Source-dependent |
| **DCCEEW / NGER**    | Emission factors                     |   Reference data |
| **Electricity Maps** | Optional carbon-intensity enrichment | Source-dependent |

All external operational data follows the general ingestion path:

```text
External Source
      ↓
DuckDB
      ↓
RabbitMQ
      ↓
PostgreSQL raw.*
      ↓
dbt
      ↓
Curated Marts
```

---

# 🧰 Technology Stack

| Layer           | Technology                        |
| --------------- | --------------------------------- |
| Backend         | FastAPI, Python 3.12+             |
| Async Tasks     | Celery                            |
| Event Bus       | RabbitMQ                          |
| Orchestration   | Prefect                           |
| Staging         | DuckDB                            |
| Warehouse       | PostgreSQL / NeonDB               |
| Transformation  | dbt                               |
| ML              | PyTorch                           |
| Forecast Models | LSTM, TFT, TimesFM                |
| Optimization    | Structured Pruning + Fine-tuning  |
| Uncertainty     | Conformal Prediction              |
| MLOps           | MLflow                            |
| Cache           | Redis                             |
| Object Storage  | Cloudflare R2                     |
| Observability   | OpenTelemetry                     |
| Metrics         | Prometheus                        |
| Logs            | Loki                              |
| Traces          | Tempo                             |
| Visualization   | Grafana                           |
| Frontend        | Next.js 15                        |
| UI              | React, Tailwind, Recharts         |
| Containers      | Docker                            |
| CI/CD           | GitHub Actions                    |
| Quality         | Ruff, Mypy, Pytest, Bandit, Trivy |

---

# 📁 Repository Structure

The repository is organized around independently deployable services.

```text
ecoLens/
│
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── CODEOWNERS
├── docker-compose.yml
├── .env.example
├── Makefile
│
├── services/
│   │
│   ├── ingestion/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── README.md
│   │   ├── tests/
│   │   └── app/
│   │       ├── collectors/
│   │       ├── anomaly/
│   │       ├── staging/
│   │       ├── events/
│   │       ├── schemas/
│   │       └── main.py
│   │
│   ├── warehouse/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── README.md
│   │   ├── tests/
│   │   ├── dbt/
│   │   │   └── ecolens/
│   │   │       ├── models/
│   │   │       │   ├── staging/
│   │   │       │   ├── intermediate/
│   │   │       │   └── marts/
│   │   │       ├── seeds/
│   │   │       └── dbt_project.yml
│   │   └── app/
│   │       ├── consumers/
│   │       ├── loaders/
│   │       └── main.py
│   │
│   ├── forecast/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── README.md
│   │   ├── tests/
│   │   └── app/
│   │       ├── api/
│   │       ├── models/
│   │       ├── forecasting/
│   │       ├── carbon/
│   │       ├── registry/
│   │       ├── calibration/
│   │       ├── drift/
│   │       └── main.py
│   │
│   └── observability/
│       ├── README.md
│       └── dashboards/
│
├── frontend/
│   └── dashboard/
│       ├── package.json
│       ├── app/
│       ├── components/
│       ├── lib/
│       └── public/
│
├── infrastructure/
│   ├── docker/
│   ├── prometheus/
│   ├── grafana/
│   ├── loki/
│   ├── tempo/
│   └── otel/
│
├── docs/
│   ├── architecture.md
│   ├── data-sources.md
│   ├── microservices.md
│   ├── observability.md
│   ├── ml-lifecycle.md
│   └── carbon-model.md
│
└── .github/
    └── workflows/
```

---

# 🚀 Quickstart

### Requirements

* Docker
* Docker Compose
* Python 3.12+
* Node.js 20+
* Git

### Clone

```bash
git clone https://github.com/diptu/ecoLens.git
cd ecoLens
```

### Configure

```bash
cp .env.example .env
```

Configure the required:

* PostgreSQL / NeonDB credentials
* RabbitMQ
* Redis
* MLflow
* Object storage
* External API credentials where required

### Start infrastructure

```bash
docker compose up -d
```

### Start services

```bash
docker compose up ingestion warehouse forecast dashboard
```

### Access locally

```text
Dashboard       http://localhost:3000
Forecast API    http://localhost:8000
API Docs        http://localhost:8000/docs
Grafana         http://localhost:3001
```

---

# 🔌 API

The Forecast service exposes versioned REST APIs.

Example resources:

```text
/v1/forecast
/v1/emissions
/v1/carbon-intensity
/v1/footprint
/v1/generation-mix
/v1/regions
/v1/model
/v1/healthz
```

The API returns structured JSON responses and OpenAPI documentation.

Example conceptual forecast response:

```json
{
  "region": "NSW1",
  "horizon": "24h",
  "forecast": {
    "p10": [],
    "p50": [],
    "p90": []
  },
  "model_version": "forecast-model-v12",
  "generated_at": "2026-08-08T00:00:00Z"
}
```

---

# 🧪 Testing & Quality

Each service maintains its own testing and quality pipeline.

### Unit tests

```bash
pytest
```

### Linting

```bash
ruff check .
```

### Formatting

```bash
ruff format .
```

### Type checking

```bash
mypy .
```

### Security

```bash
bandit -r .
```

Container images are additionally scanned using Trivy.

CI validates code quality before a service can be released.

---

# 🔐 Security

Security principles include:

* Non-root containers
* Least-privilege service accounts
* Secret management through environment/configuration systems
* No direct database access from the frontend
* Internal-only data pipeline services
* API authentication and authorization
* Dependency scanning
* Container scanning
* Static security analysis
* Secret scanning
* SBOM generation
* Signed production images where supported

---

# 🚢 Deployment

ecoLens is designed to support both local Docker deployment and cloud-native
deployment.

### Local

```text
Docker Compose
     │
     ├── Services
     ├── RabbitMQ
     ├── Redis
     ├── PostgreSQL
     ├── MLflow
     └── Observability
```

### Production

```text
                    GitHub
                       │
                       ▼
                 CI / Testing
                       │
                       ▼
                Container Registry
                       │
                       ▼
                 Deployment Layer
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        Application          Observability
         Services              Stack
             │
       ┌─────┼─────┐
       ▼     ▼     ▼
   Ingestion Warehouse Forecast
```

Services can be independently scaled according to workload.

---

# 📈 Performance & Reliability

The platform is designed around several operational goals:

### Ingestion

* Preserve source data fidelity
* Avoid blocking on warehouse processing
* Handle temporary provider failures
* Support retryable event processing

### Forecasting

* Low-latency inference
* Redis caching
* Model health monitoring
* Fallback model support
* Probabilistic calibration

### Warehousing

* Idempotent ingestion
* Raw-data preservation
* Incremental dbt transformations
* Historical reprocessing

### Observability

* Centralized telemetry
* Service-level metrics
* Distributed tracing
* Pipeline monitoring
* ML performance monitoring

---

# 🗺️ Roadmap

## Data Engineering

* [x] Multi-source energy ingestion
* [x] DuckDB staging
* [x] Event-driven warehouse ingestion
* [x] PostgreSQL raw layer
* [x] dbt analytical layer
* [ ] Expanded historical backfill framework
* [ ] Data lineage visualization

## Machine Learning

* [x] LSTM forecasting
* [x] Probabilistic forecasting
* [x] Conformal calibration
* [ ] TFT production integration
* [ ] TimesFM integration
* [ ] Incremental learning
* [ ] Automated drift-driven retraining
* [ ] Structured model pruning pipeline
* [ ] Automated model champion/challenger evaluation

## Carbon Intelligence

* [x] Carbon intensity estimation
* [x] Generation-mix integration
* [x] Carbon footprint calculation
* [ ] Forecast carbon intensity
* [ ] Forecast emissions by generation source
* [ ] Facility-level carbon intelligence

## MLOps

* [x] MLflow tracking
* [x] Model registry
* [x] Model versioning
* [ ] Automated promotion gates
* [ ] Champion/challenger deployment
* [ ] Automated rollback

## Observability

* [x] OpenTelemetry instrumentation
* [x] Prometheus metrics
* [x] Loki logs
* [x] Tempo traces
* [x] Grafana dashboards
* [ ] Automated retraining recommendations
* [ ] Unified data-quality + model-performance dashboard

## Frontend

* [x] Real-time energy dashboard
* [x] Forecast visualization
* [x] Carbon visualization
* [ ] Model performance dashboard
* [ ] Data quality dashboard
* [ ] Forecast uncertainty dashboard
* [ ] Operational alerting

---

# 🤝 Contributing

Contributions are welcome.

Before submitting a pull request:

1. Run the relevant service tests.
2. Run Ruff.
3. Run Mypy.
4. Run security checks where applicable.
5. Update documentation for architectural changes.
6. Add tests for new functionality.
7. Keep service boundaries intact.

For service-specific contribution guidelines, see the corresponding service
`README.md`.

---

# 📄 License & Attribution

ecoLens is released under the MIT License.

Energy and environmental data remain subject to the licences and attribution
requirements of their respective providers.

See:

* [`LICENSE`](LICENSE)
* [`docs/data-sources.md`](docs/data-sources.md)
* [`docs/carbon-model.md`](docs/carbon-model.md)

for detailed licensing and attribution information.

---

# 👨‍💻 Maintainer

**Nazmul Alam**

Software Engineer · Data & ML Systems

---

<div align="center">

### 🌱 ecoLens

**From electricity data → to forecasts → to carbon intelligence.**

</div>
