"""CLI for the warehouse runner.

Usage
=====
    # Full refresh (weekly, e.g. Sunday)
    python -m ecolens.warehouse.runner.runner --full

    # Incremental (default; 30-min cron)
    python -m ecolens.warehouse.runner.runner --incremental

    # Validate only (no dbt run; just check current state)
    python -m ecolens.warehouse.runner.runner --validate-only

    # Run a specific dbt tag
    python -m ecolens.warehouse.runner.runner --select tag:ml_features
"""

from __future__ import annotations

import argparse
import asyncio
import shutil

from .orchestrator import WarehouseRunner
from .settings import get_warehouse_runner_settings


def _check_dependencies() -> dict[str, bool]:
    return {"dbt (cli)": shutil.which("dbt") is not None}


def _show_example() -> int:
    """Show what a typical run's output looks like."""
    print("=" * 70)
    print("ecoLens warehouse runner — example run output")
    print("=" * 70)
    print()
    print("$ python -m ecolens.warehouse.runner.runner --incremental")
    print()
    print(
        "  2026-07-21 12:30:00 [info]   runner.start                         mode='incremental'"
    )
    print(
        "  2026-07-21 12:30:00 [info]   source_freshness.connected           uri='mongodb://...'"
    )
    print(
        "  2026-07-21 12:30:01 [info]   source_freshness.check               fresh=True sources=5"
    )
    print(
        "  2026-07-21 12:30:01 [info]   dbt.invoke                           cmd='dbt build --threads 1'"
    )
    print(
        "  2026-07-21 12:30:47 [info]   dbt.complete                        cmd='build' success=True duration_s=46.0 rows=1234"
    )
    print(
        "  2026-07-21 12:30:47 [info]   data_quality.validate                violations=0 success=True"
    )
    print(
        "  2026-07-21 12:30:48 [info]   aggregate_refresh.view              view='mv_daily_national_demand' latency_ms=42"
    )
    print(
        "  2026-07-21 12:30:48 [info]   metrics.emitted                     path='data/log/warehouse-runs.jsonl'"
    )
    print(
        "  2026-07-21 12:30:48 [info]   runner.complete                     success=True duration_s=48.0 stages=5"
    )
    print()
    print("  data/log/warehouse-runs.jsonl:")
    print('  {"started_at": "2026-07-21T12:30:00+00:00",')
    print('   "finished_at": "2026-07-21T12:30:48+00:00",')
    print('   "duration_seconds": 48.0,')
    print('   "success": true,')
    print('   "stages": [')
    print('     {"name": "source_freshness", "success": true, ...},')
    print('     {"name": "dbt_build", "rows_affected": 1234, "success": true, ...},')
    print('     {"name": "data_quality", "violations": 0, "success": true, ...},')
    print("     ...")
    print("   ]}")
    print()
    print("=" * 70)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ecoLens warehouse runner — orchestrates the dbt pipeline"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--incremental",
        action="store_true",
        default=True,
        help="incremental run (default; 30-min cron)",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="full refresh with --full-refresh (weekly)",
    )
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="check source freshness + warehouse state, skip dbt",
    )
    parser.add_argument(
        "--select",
        nargs="+",
        default=None,
        help="dbt --select (e.g. tag:ml_features, +fact_demand_30min)",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=None,
        help="dbt --exclude (e.g. tag:dev)",
    )
    parser.add_argument(
        "--skip-aggregates",
        action="store_true",
        help="skip materialized view refresh",
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="skip archive + vacuum stage",
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="show example output and exit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.example:
        return _show_example()

    deps = _check_dependencies()
    print("=" * 70)
    print("ecoLens warehouse runner")
    print("=" * 70)
    for name, ok in deps.items():
        print(f"  {name:<12}  {'✓' if ok else '✗'}")
    print()

    mode = "incremental"
    if args.full:
        mode = "full"
    elif args.validate_only:
        mode = "validate"

    runner = WarehouseRunner(get_warehouse_runner_settings())
    result = asyncio.run(
        runner.run(
            mode=mode,
            dbt_select=args.select,
            dbt_exclude=args.exclude,
            skip_aggregates=args.skip_aggregates,
            skip_archive=args.skip_archive,
        )
    )

    print("=" * 70)
    print(f"  mode:           {mode}")
    print(f"  success:        {result.success}")
    print(f"  duration:       {result.duration_seconds:.1f}s")
    print(f"  stages:         {len(result.stages)}")
    print(f"  rows affected:  {sum(s.rows_affected for s in result.stages)}")
    print("=" * 70)
    for s in result.stages:
        marker = "✓" if s.success else "✗"
        print(
            f"  {marker} {s.name:<25}  duration={s.duration_seconds:.1f}s  rows={s.rows_affected}"
        )
        if s.error:
            print(f"      error: {s.error}")
    print("=" * 70)
    return 0 if result.success else 1


__all__ = ["main", "parse_args"]
