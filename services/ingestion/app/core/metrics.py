"""Prometheus metrics for the ingestion service.

The ingest domain only — the subset of data-pipeline's `core/metrics.py`
that `pipeline.tasks._common.standard_run` actually populates (dbt/ML/
forecast metrics don't apply, this service doesn't touch any of that).
Served at `GET /metrics` (`api/v1/health/routes.py`).
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

# Standard Prometheus "info metric" pattern -- see data-pipeline's
# identical `build_info` for the full reasoning (services/observility's
# Observability Contract, why this beats a hardcoded scrape-config
# label).
build_info = Gauge(
    "ecolens_build_info",
    "Always 1 -- service identity via labels.",
    ["service", "version"],
    registry=REGISTRY,
)
build_info.labels(service="ingestion", version=__version__).set(1)

# `outcome` is "success" (fetch+stage completed, including the
# zero-rows no-op case) or "failure" (fetch/staging raised) -- mirrors
# `meta._ingest_log`'s own terminal states at the point `standard_run`
# itself resolves, before a later consumer (whichever service still
# runs `pipeline.warehouse_sync`) closes a `"staged"` row out to
# `"success"`/`"sync_failed"`. Backs `ecolens:ingest_success_rate_24h`
# (services/observility/prometheus/rules/ingestion.yml) -- was defined
# in data-pipeline's own `core/metrics.py` but never actually
# incremented by either service's `_common.py` until now.
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


def metrics_as_text() -> bytes:
    """Render the registry in Prometheus text-exposition format."""
    return generate_latest(REGISTRY)
