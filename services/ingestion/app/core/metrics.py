"""Prometheus metrics for the ingestion service.

The ingest domain only — the subset of data-pipeline's `core/metrics.py`
that `pipeline.tasks._common.standard_run` actually populates (dbt/ML/
forecast metrics don't apply, this service doesn't touch any of that).
A `/metrics` endpoint exposing this registry is still Phase 3's job
("Publish Prometheus Metrics") — these objects exist now because
`standard_run` (Phase 1's "Port Resiliency & Anomaly Logic") writes to
them, not because they're served anywhere yet.
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

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
