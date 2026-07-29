"""ecoLens warehouse event consumer — entry point.

Long-running daemon: listens on RabbitMQ for "data ingested" events
(published by `duckdb_store.write_historical`) and triggers debounced,
overlap-guarded incremental `WarehouseRunner` runs -- see
`event_consumer.py`'s module docstring for the full design. This is
the event-driven replacement for the old every-30-min warehouse cron.

Usage
=====
    uv run --active python -m ecolens.warehouse.core.event_consumer_entrypoint

Runs until killed (SIGINT/SIGTERM/Ctrl-C) -- meant to be kept alive by
`scripts/warehouse_consumer_supervisor.sh`, not run directly under
cron: cron runs periodic jobs that start and exit, not always-on
daemons, so a plain crontab entry would just restart this every N
minutes rather than keep one instance continuously listening.
"""

from __future__ import annotations

import asyncio
import sys

from ecolens.config import get_settings
from ecolens.shared.observability.logging import get_logger
from ecolens.warehouse.service.event_consumer import WarehouseEventConsumer

log = get_logger(__name__)


async def _main() -> int:
    settings = get_settings()
    consumer = WarehouseEventConsumer()
    log.info(
        "event_consumer.starting",
        queue=settings.rabbitmq_queue,
    )
    try:
        await consumer.run_forever(settings.rabbitmq_url, settings.rabbitmq_queue)
    finally:
        await consumer.stop()
    return 0


def main() -> int:
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
