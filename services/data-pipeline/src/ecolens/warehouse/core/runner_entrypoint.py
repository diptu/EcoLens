"""ecoLens warehouse runner — entry point.

Orchestrates the DuckDB -> dbt -> PostgreSQL pipeline that keeps the
ecoLens warehouse fresh.

What it does
============
    ┌──────────────┐
    │  DuckDB      │  raw tables (aemo_nem_dispatch, bom_observations, ...)
    └──────┬───────┘
           │
           │  Stage 1: source freshness check
           │
    ┌──────▼──────────────────────────────────────────────┐
    │  dbt build  (staging → intermediate → marts)        │
    │    - staging:  1:1 views over raw.* (synced from DuckDB) │
    │    - intermediate:  joins + grain alignment         │
    │    - marts:  fact_demand_30min, ml_features, dims   │
    └──────┬──────────────────────────────────────────────┘
           │
           │  Stage 2: data quality validation
           │
    ┌──────▼──────────────────────────────────────────────┐
    │  Warehouse  (PostgreSQL)                            │
    │    - fact_demand_30min  (1M rows/yr)                │
    │    - ml_features_demand_v1  (with 48 lags)         │
    │    - dim_region, dim_holiday, dim_calendar         │
    └─────────────────────────────────────────────────────┘

This runner coordinates all of that. `--incremental` runs are normally
triggered by `ecolens.warehouse.service.event_consumer` in response to
a RabbitMQ "data ingested" event, not a fixed schedule (see that
module's docstring for the full design); `--full` is a manual/as-needed
operation. See `warehouse/werehouse.md` for the overall pipeline design.

Split by concern (unlike the original single-file draft):
  settings.py       WarehouseRunnerSettings — pg/dbt/threshold tuning
  models.py         StageResult / RunResult dataclasses
  freshness.py       Stage 1 — SourceFreshnessChecker (DuckDB)
  dbt_runner.py     Stage 2 — DbtRunner (dbt build via subprocess)
  quality.py        Stage 3 — DataQualityValidator (freshness/nulls/gaps)
  aggregates.py     Stage 4 — AggregateRefresher (REFRESH MATERIALIZED VIEW)
  metrics.py        Stage 5 — MetricsEmitter (JSONL + human-readable log)
  archive.py        Stage 6 — ArchiveManager (no-op archive + Postgres VACUUM)
  orchestrator.py   WarehouseRunner — runs all 6 stages in order
  cli.py            argparse CLI (--full / --incremental / --validate-only / --select)
  runner.py         this file — entry point, `if __name__ == "__main__"`

Usage
=====
    # Full refresh (weekly, e.g. Sunday)
    uv run --active python -m ecolens.warehouse.core.runner_entrypoint --full

    # Incremental (default; normally triggered by event_consumer, not cron)
    uv run --active python -m ecolens.warehouse.core.runner_entrypoint --incremental

    # Validate only (no dbt run; just check current state)
    uv run --active python -m ecolens.warehouse.core.runner_entrypoint --validate-only

    # Run a specific dbt tag
    uv run --active python -m ecolens.warehouse.core.runner_entrypoint --select tag:ml_features
"""

from __future__ import annotations

import sys

from ecolens.warehouse.service.orchestrator import WarehouseRunner

from .cli import main

__all__ = ["main", "WarehouseRunner"]

if __name__ == "__main__":
    sys.exit(main())
