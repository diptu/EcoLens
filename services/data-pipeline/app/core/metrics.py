"""Prometheus metrics for the data-pipeline service.

One registry, four domains: ingest, dbt, ML, forecast. `metrics_as_text()`
renders the current registry in Prometheus text-exposition format for the
`GET /metrics` endpoint (ECO-D15).
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app import __version__

REGISTRY = CollectorRegistry()

# Standard Prometheus "info metric" pattern -- always 1, the labels carry
# the actual data. Closes part of README's "Observability Contract"
# (services/observility/README.md: every metric should be identifiable by
# `service=`/`version=`) without needing a separate `/version` endpoint
# or a hardcoded label in the scrape config that would drift the moment
# this service ships a new version without someone remembering to update
# it there too -- this way the number scraped is always whatever's
# actually running. `environment=` is deliberately not repeated here --
# that's Prometheus's own `external_labels.environment`
# (services/observility/prometheus/prometheus.yml), which already
# applies to every series scraped from every job, including this one.
build_info = Gauge(
    "ecolens_build_info",
    "Always 1 -- service identity via labels.",
    ["service", "version"],
    registry=REGISTRY,
)
build_info.labels(service="data-pipeline", version=__version__).set(1)

# Ingest (ECO-D24-D29)
ingest_runs_total = Counter(
    "ecolens_ingest_runs_total",
    "Ingestion runs, by source and outcome.",
    ["source", "outcome"],
    registry=REGISTRY,
)
ingest_duration_seconds = Histogram(
    "ecolens_ingest_duration_seconds",
    "Ingestion run duration in seconds, by source.",
    ["source"],
    registry=REGISTRY,
)
ingest_rows_total = Counter(
    "ecolens_ingest_rows_total",
    "Rows landed, by source.",
    ["source"],
    registry=REGISTRY,
)
ingest_failures_total = Counter(
    "ecolens_ingest_failures_total",
    "Ingestion run failures, by source.",
    ["source"],
    registry=REGISTRY,
)
latest_ingest_ts = Gauge(
    "ecolens_latest_ingest_timestamp_seconds",
    "Unix timestamp of the most recent successful ingest, by source.",
    ["source"],
    registry=REGISTRY,
)
# Numeric-encoded so it's a single gauge (Grafana state-timeline panel
# reads this directly) rather than 3 separate boolean gauges. Set by
# pipeline.tasks._common.standard_run's wrapper right after it reads
# breaker.state for meta._ingest_log's circuit_breaker_state column --
# same read, also pushed here, rather than a second Redis round-trip.
circuit_breaker_state = Gauge(
    "ecolens_circuit_breaker_state",
    "Circuit breaker state, by source. 0=closed, 1=half_open, 2=open.",
    ["source"],
    registry=REGISTRY,
)

# dbt (ECO-D21)
dbt_run_duration_seconds = Histogram(
    "ecolens_dbt_run_duration_seconds",
    "dbt subcommand duration in seconds, by subcommand.",
    ["subcommand"],
    registry=REGISTRY,
)
dbt_runs_total = Counter(
    "ecolens_dbt_runs_total",
    "dbt subcommand invocations, by subcommand and outcome.",
    ["subcommand", "outcome"],
    registry=REGISTRY,
)

# ML training (ECO-D35-D43)
ml_training_duration_seconds = Histogram(
    "ecolens_ml_training_duration_seconds",
    "Model training duration in seconds, by model name.",
    ["model_name"],
    registry=REGISTRY,
)
ml_training_runs_total = Counter(
    "ecolens_ml_training_runs_total",
    "Training runs, by model name and outcome.",
    ["model_name", "outcome"],
    registry=REGISTRY,
)
ml_last_mape = Gauge(
    "ecolens_ml_last_mape",
    "Most recent rolling-28d MAPE, by model name.",
    ["model_name"],
    registry=REGISTRY,
)

# Forecast (ECO-D44)
forecast_requests_total = Counter(
    "ecolens_forecast_requests_total",
    "Forecast requests served, by region.",
    ["region"],
    registry=REGISTRY,
)
forecast_latency_seconds = Histogram(
    "ecolens_forecast_latency_seconds",
    "Forecast endpoint latency in seconds.",
    registry=REGISTRY,
)


def metrics_as_text() -> bytes:
    """Render the registry in Prometheus text-exposition format."""
    return generate_latest(REGISTRY)
