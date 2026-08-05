"""Prometheus metrics for the warehouse service (README Phase 5 —
"Configure metrics collection for queue latency, failed consumer
events, dbt test failures, and database storage consumption trends").

Populated by the modules that actually do the work (`consumers.landed_events`,
`retention.*`, `loaders.dbt_runner`) — this module just defines the
registry/instruments in one place, same "objects exist because the hot
path writes to them" shape `services/ingestion`'s identical module uses.
`GET /metrics` (`api/v1/health/routes.py`) is what actually serves this.
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

consume_duration_seconds = Histogram(
    "ecolens_warehouse_consume_duration_seconds",
    "Time to sync one landed event into Postgres raw.*, by source.",
    ["source"],
    registry=REGISTRY,
)
rows_loaded_total = Counter(
    "ecolens_warehouse_rows_loaded_total",
    "Rows actually inserted into raw.* (excluding ON CONFLICT DO NOTHING skips), by source.",
    ["source"],
    registry=REGISTRY,
)
consume_failures_total = Counter(
    "ecolens_warehouse_consume_failures_total",
    "Landed-event consume failures (nacked to the DLQ), by source.",
    ["source"],
    registry=REGISTRY,
)
queue_message_age_seconds = Histogram(
    "ecolens_warehouse_queue_message_age_seconds",
    "Age of a landed-event message (publish time to consume time) when picked up.",
    registry=REGISTRY,
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)
dbt_test_failures_total = Counter(
    "ecolens_warehouse_dbt_test_failures_total",
    "dbt test failures, by test name.",
    ["test_name"],
    registry=REGISTRY,
)
dbt_run_duration_seconds = Histogram(
    "ecolens_warehouse_dbt_run_duration_seconds",
    "Time to run one dbt subcommand, by subcommand.",
    ["subcommand"],
    registry=REGISTRY,
)
dbt_runs_total = Counter(
    "ecolens_warehouse_dbt_runs_total",
    "dbt subprocess invocations, by subcommand and outcome (success/failure).",
    ["subcommand", "outcome"],
    registry=REGISTRY,
)
database_size_bytes = Gauge(
    "ecolens_warehouse_database_size_bytes",
    "Total Postgres database size, as last measured by the size monitor.",
    registry=REGISTRY,
)
retention_rows_pruned_total = Counter(
    "ecolens_warehouse_retention_rows_pruned_total",
    "Rows deleted by the retention job, by table.",
    ["table"],
    registry=REGISTRY,
)
coldstorage_export_rows_total = Counter(
    "ecolens_warehouse_coldstorage_export_rows_total",
    "Rows exported to R2 cold storage before pruning, by table.",
    ["table"],
    registry=REGISTRY,
)


def metrics_as_text() -> bytes:
    return generate_latest(REGISTRY)
