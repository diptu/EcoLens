"""Manually trigger a MongoDB -> PostgreSQL `raw.*` sync (no dbt run).

Standalone script (not a pytest test): copies each source's MongoDB
collection into its `raw.*` Postgres table via `RawSyncer`. Useful for
debugging the sync step in isolation from the rest of the warehouse
pipeline (`make warehouse` runs this as part of a full run; this script
is the same sync, on its own).

Run directly:

    uv run --active ./scripts/sync_raw.py                # incremental (default lookback)
    uv run --active ./scripts/sync_raw.py --full          # resync full history
    uv run --active ./scripts/sync_raw.py --lookback-days 10
"""

import argparse
import asyncio

from ecolens.ingestion.storage.postgres import RawSyncer, default_lookback
from ecolens.shared.observability.logging import get_logger
from ecolens.warehouse.runner.settings import get_warehouse_runner_settings

log = get_logger("sync_raw")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="resync every document in each collection (ignores --lookback-days)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="incremental window in days (default: settings.raw_sync_lookback_days)",
    )
    return parser.parse_args()


async def run(*, full: bool, lookback_days: int | None) -> None:
    settings = get_warehouse_runner_settings()
    since = None
    if not full:
        since = default_lookback(lookback_days or settings.raw_sync_lookback_days)

    syncer = RawSyncer(pg_settings=settings)
    await syncer.connect()
    try:
        results = await syncer.sync_all(since=since)
    finally:
        await syncer.close()

    log.info("sync.complete", since=since.isoformat() if since else "full", **results)
    print("=" * 60)
    print(f"raw sync {'(full)' if full else f'(since {since})'}")
    print("=" * 60)
    for source, count in results.items():
        print(f"  {source:<20} {count} rows")
    print("=" * 60)
    print(f"  total: {sum(results.values())} rows")


if __name__ == "__main__":
    cli_args = parse_args()
    asyncio.run(run(full=cli_args.full, lookback_days=cli_args.lookback_days))
