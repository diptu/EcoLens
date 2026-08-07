# Observability Service

Centralized observability infrastructure for the platform's independently maintained microservices.

The platform currently consists of three separate services:

* **Ingestion Service** — collects operational energy data
* **Warehouse Service** — transforms and manages analytical data
* **Forecast Service** — generates energy demand forecasts

Each service is maintained in its own Git repository by a separate team. This repository provides a **centralized observability layer** without creating tight coupling or unnecessary communication between services.

---

## Architecture

```text
                    ┌──────────────────────────────┐
                    │      Observability Stack      │
                    │                              │
                    │  OpenTelemetry Collector     │
                    │  Prometheus                  │
                    │  Loki                        │
                    │  Tempo                       │
                    │  Grafana                     │
                    │  Alertmanager                │
                    └───────────────▲──────────────┘
                                    │
                         Telemetry Collection
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
      ┌───────┴────────┐    ┌───────┴────────┐    ┌───────┴────────┐
      │   Ingestion    │    │   Warehouse    │    │    Forecast    │
      │    Service     │    │    Service     │    │     Service    │
      │                │    │                │    │                │
      │ /metrics       │    │ /metrics       │    │ /metrics       │
      │ JSON Logs      │    │ JSON Logs      │    │ JSON Logs      │
      │ OTel Traces    │    │ OTel Traces    │    │ OTel Traces    │
      └────────────────┘    └────────────────┘    └────────────────┘
```

---

## Design Principle

The observability service **does not actively communicate with business services for every event**.

Instead, each microservice emits lightweight telemetry:

```text
Microservice
    │
    ├── Metrics ────────► Prometheus
    │
    ├── Logs ───────────► Loki
    │
    └── Traces ─────────► OpenTelemetry Collector ──► Tempo
                                                        │
                                                        ▼
                                                     Grafana
```

This prevents the observability layer from becoming a source of traffic or coupling between services.

---

## What Each Service Needs to Provide

Every microservice should implement the same minimal observability contract.

### 1. Metrics

Expose:

```text
GET /metrics
```

Example metrics:

```text
http_requests_total
http_request_duration_seconds
http_errors_total
service_up
```

Service-specific metrics can also be added:

```text
ingestion_records_processed_total
warehouse_jobs_completed_total
forecast_predictions_total
forecast_latency_seconds
```

Prometheus periodically scrapes these endpoints.

---

### 2. Structured Logs

Services should write logs to `stdout` using structured JSON.

Example:

```json
{
  "timestamp": "2026-08-06T10:15:00Z",
  "level": "ERROR",
  "service": "forecast",
  "event": "prediction_failed",
  "request_id": "abc123",
  "error": "model timeout"
}
```

The services do **not** send logs directly to the observability service.

A log collector such as Fluent Bit, Vector, or an equivalent agent collects them.

---

### 3. Distributed Tracing

Use OpenTelemetry instrumentation.

Example:

```text
Ingestion
    │
    └── Warehouse
            │
            └── Forecast
```

A trace allows the team to understand the complete lifecycle of a request/job without requiring the services to directly communicate with the observability platform.

---

### 4. Health Endpoints

Each service should expose:

```text
GET /health
GET /ready
```

Example:

```json
{
  "status": "healthy"
}
```

These endpoints can be used by Kubernetes, load balancers, or monitoring systems.

---

# Technology Stack

| Component      | Responsibility                           |
| -------------- | ---------------------------------------- |
| OpenTelemetry  | Telemetry instrumentation and collection |
| OTel Collector | Central telemetry gateway                |
| Prometheus     | Metrics storage and querying             |
| Loki           | Log aggregation                          |
| Tempo          | Distributed tracing                      |
| Grafana        | Dashboards and visualization             |
| Alertmanager   | Alert routing and notification           |

---

# Repository Structure

As actually implemented (two additions beyond the original sketch above
— see `TODO.md`'s "Deviations" section for why: this stack's own
"Structured Logs" and "Recommended Alert Examples" sections above imply
both, so they're here rather than left as a documented-but-missing gap):

```text
services/observility/
│
├── docker-compose.yml
├── .env.example
├── README.md
├── TODO.md
│
├── otel/
│   └── otel-collector-config.yml
│
├── prometheus/
│   ├── prometheus.yml
│   └── rules/
│       ├── ingestion.yml
│       ├── warehouse.yml
│       ├── forecast.yml
│       └── platform.yml
│
├── grafana/
│   ├── dashboards/
│   │   ├── platform.json
│   │   ├── ingestion.json
│   │   ├── warehouse.json
│   │   └── forecast.json
│   │
│   └── provisioning/
│       ├── datasources/datasources.yml
│       └── dashboards/dashboards.yml
│
├── loki/
│   └── loki-config.yml
│
├── promtail/                      # not in the original sketch --
│   └── promtail-config.yml        # the actual log *collector* (README's
│                                   # own "Structured Logs" section) --
│                                   # Loki alone only stores what's pushed to it
│
├── tempo/
│   └── tempo-config.yml
│
└── alertmanager/
    └── alertmanager.yml.template  # `.template`, not `alertmanager.yml` --
                                    # rendered via envsubst at container
                                    # start, see the file's own header
```

cAdvisor (container-level CPU/memory metrics, backing the Platform
alerts' "High CPU / memory usage") needs no config file of its own —
it's just a `cadvisor` service entry in `docker-compose.yml`.

---

# Service Integration

Each team integrates observability independently in its own repository.

For example:

```text
ingestion-service/
    └── OpenTelemetry + /metrics

warehouse-service/
    └── OpenTelemetry + /metrics

forecast-service/
    └── OpenTelemetry + /metrics
```

The teams do **not** need to modify their business logic to communicate with the observability service.

---

# Avoiding Observability Spam

The observability platform should follow these rules:

### Metrics

Use periodic scraping rather than pushing every metric event.

```text
Prometheus ──scrape──► /metrics
```

### Logs

Use asynchronous collection.

```text
stdout → log collector → Loki
```

### Traces

Use batching.

```text
Service → OTel SDK → OTel Collector → Tempo
```

The OTel Collector should batch and buffer telemetry before forwarding it.

---

# Ownership Model

| Responsibility            | Service Team | Observability Team |
| ------------------------- | -----------: | -----------------: |
| `/metrics` endpoint       |            ✅ |                    |
| Structured logging        |            ✅ |                    |
| OTel instrumentation      |            ✅ |                    |
| Business-specific metrics |            ✅ |                    |
| Collector infrastructure  |              |                  ✅ |
| Prometheus                |              |                  ✅ |
| Loki                      |              |                  ✅ |
| Tempo                     |              |                  ✅ |
| Grafana                   |              |                  ✅ |
| Alert rules               |       Shared |                  ✅ |
| Dashboards                |       Shared |                  ✅ |

This keeps the three service teams autonomous while maintaining a common observability standard.

---

# Recommended Alert Examples

### Ingestion

```text
High ingestion failure rate
No data received for X minutes
External provider API failures
Ingestion latency above threshold
```

### Warehouse

```text
Warehouse job failures
Pipeline processing delay
Data quality failures
Database connection errors
```

### Forecast

```text
Forecast job failures
Prediction latency above threshold
Missing forecast output
Model inference errors
```

### Platform

```text
High CPU / memory usage
Service unavailable
High HTTP error rate
High request latency
Telemetry collector failure
```

---

# Observability Contract

All services should follow a common naming convention.

```text
service=<service-name>
environment=<dev|staging|production>
version=<service-version>
```

Example:

```text
service="forecast"
environment="production"
version="1.4.2"
```

This allows Grafana dashboards and Prometheus queries to work consistently across all services.

---

# Deployment

The observability stack should be deployed independently from the business services.

```text
                    Production
                        │
          ┌─────────────┴─────────────┐
          │                           │
    Business Services          Observability
          │                           │
   ┌──────┼──────┐            ┌───────┼───────┐
   │      │      │            │       │       │
Ingestion Warehouse Forecast  Prometheus Loki Tempo
                                  │
                                Grafana
```

A failure in Grafana or the observability UI should **not stop** ingestion, warehouse processing, or forecasting.

## Running this stack

This is a separate Docker Compose project from the root `ecolens` stack
(`../../docker-compose.yml`). By default it attaches to that stack's own
default network (`ecolens_default`, declared `external`) to reach the
business services for scraping/log collection, so **the root stack must
already be running first** if you're using the default targets:

```bash
# from the repo root, if not already running:
docker compose up -d

# then, from this directory:
cd services/observility
cp .env.example .env
# edit .env: set a real GRAFANA_ADMIN_PASSWORD and a real ALERTMANAGER_WEBHOOK_URL
docker compose up -d
```

Monitoring a service that's deployed on a different machine instead?
Prometheus's scrape targets are env-driven
(`DATA_PIPELINE_TARGET`/`INGESTION_TARGET`/`WAREHOUSE_TARGET`/
`FORECAST_API_TARGET` in `.env.example`) — point the relevant one at a
real `host:port` reachable from wherever this stack runs, and that
service no longer needs to be reachable via `ecolens_default` at all.
See `../../docs/runbooks/independent-service-deployment.md` for the
full picture of what else changes once services aren't all on one
machine (Promtail/log collection is still Docker-socket-scoped to this
one host, though — it only ever sees containers running alongside it).

- All secrets (Grafana admin credentials, the Alertmanager webhook destination) live in `.env`, which is gitignored — nothing sensitive is committed. `docker compose` refuses to start without them.
- If you're deploying against a `grafanadata` volume that was ever initialized before this hardening pass, the admin password in `.env` won't take effect on its own — run `docker exec ecolens-observability-grafana-1 grafana-cli admin reset-admin-password <password>` once. `GF_SECURITY_ADMIN_PASSWORD` only seeds a *fresh* install.
- Image versions are pinned (see `docker-compose.yml`); bump them deliberately, not via `:latest`.
- Prometheus/Loki/Tempo retention are all configured explicitly via `.env` — see `.env.example` for current defaults and where to tune them.
- `docker compose ps` should show `(healthy)` for prometheus, alertmanager, cadvisor, loki, tempo, and grafana. `otel-collector` and `promtail` have no container-level healthcheck (the otel-collector image has no shell to run one, per its own upstream image; promtail's own container likewise ships none) — `otel-collector`'s `:13133/health` endpoint is available for external monitoring instead.
- Host ports are deliberately offset from the root stack's own (now-superseded, see `TODO.md`) inline prometheus/alertmanager/grafana/loki — see the table below.

| Component      | URL                          |
| -------------- | ----------------------------- |
| Prometheus     | http://localhost:9091          |
| Alertmanager   | http://localhost:9094          |
| Grafana        | http://localhost:3002 (admin / `$GRAFANA_ADMIN_PASSWORD`) |
| Loki           | http://localhost:3101 (query via Grafana, not directly) |
| Tempo          | http://localhost:3200 (query via Grafana, not directly) |
| OTel Collector | grpc `localhost:4317` / http `localhost:4318` (point a service's `OTEL_EXPORTER_OTLP_ENDPOINT` here); health at `localhost:13133/health` |
| cAdvisor       | http://localhost:8085          |

See `TODO.md` for known gaps (which business services don't export
`/metrics` or traces yet) before assuming an empty panel means this
stack is broken.

---

# Key Benefits

* **Loose coupling** between services and observability
* **Independent Git repositories and teams**
* Centralized dashboards and alerts
* Standardized metrics, logs, and traces
* Minimal changes required in existing services
* Asynchronous telemetry collection
* Reduced risk of observability traffic affecting production workloads
* Easier debugging across service boundaries

---

## Guiding Principle

> **Services produce telemetry; the observability platform consumes and analyzes it.**

The observability system should monitor the platform without becoming part of the platform's critical business execution path.
