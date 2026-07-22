"""ecoLens warehouse runner — entry point.

Orchestrates the MongoDB -> dbt -> PostgreSQL pipeline that keeps the
ecoLens warehouse fresh.

What it does
============
    ┌──────────────┐
    │  MongoDB     │  raw collections (aemo_nem_dispatch, bom_observations, ...)
    └──────┬───────┘
           │
           │  Stage 1: source freshness check
           │
    ┌──────▼──────────────────────────────────────────────┐
    │  dbt build  (staging → intermediate → marts)        │
    │    - staging:  1:1 views over MongoDB               │
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

This runner coordinates all of that. It runs from a 30-min cron
(see `warehouse/werehouse.md` for the pipeline design / crontab
rhythm).

Split by concern (unlike the original single-file draft):
  settings.py       WarehouseRunnerSettings — pg/mongo/dbt/threshold tuning
  models.py         StageResult / RunResult dataclasses
  freshness.py       Stage 1 — SourceFreshnessChecker (MongoDB)
  dbt_runner.py     Stage 2 — DbtRunner (dbt build via subprocess)
  quality.py        Stage 3 — DataQualityValidator (freshness/nulls/gaps)
  aggregates.py     Stage 4 — AggregateRefresher (REFRESH MATERIALIZED VIEW)
  metrics.py        Stage 5 — MetricsEmitter (JSONL + human-readable log)
  archive.py        Stage 6 — ArchiveManager (Mongo TTL delete + VACUUM)
  orchestrator.py   WarehouseRunner — runs all 6 stages in order
  cli.py            argparse CLI (--full / --incremental / --validate-only / --select)
  runner.py         this file — entry point, `if __name__ == "__main__"`

Usage
=====
    # Full refresh (weekly, e.g. Sunday)
    uv run --active python -m ecolens.warehouse.runner.runner --full

    # Incremental (default; 30-min cron)
    uv run --active python -m ecolens.warehouse.runner.runner --incremental

    # Validate only (no dbt run; just check current state)
    uv run --active python -m ecolens.warehouse.runner.runner --validate-only

    # Run a specific dbt tag
    uv run --active python -m ecolens.warehouse.runner.runner --select tag:ml_features
"""

from __future__ import annotations

import sys

from .cli import main
from .orchestrator import WarehouseRunner

__all__ = ["main", "WarehouseRunner"]

if __name__ == "__main__":
    sys.exit(main())
