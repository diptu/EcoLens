"""Warehouse-sync consumer entrypoint (`ecolens-pipeline worker`, the
`warehouse-sync` docker-compose service) — the long-running half of the
raw-landing pipeline that `pipeline.tasks._common.standard_run` (the
short-lived, cron-triggered half) publishes events for.

See `pipeline.warehouse_sync.sync_landed_event` for the per-message
handler and `mq.rabbitmq_client.consume_landed_events` for the consume
loop itself — this module just wires the two together and is what an
external process (CLI, container `command:`) actually runs.
"""

from __future__ import annotations

from app.db.rabbitmq import close_rabbitmq, consume_landed_events
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.service.pipeline.warehouse_sync import sync_landed_event

log = get_logger(__name__)


async def run() -> None:
    """Run forever, syncing DuckDB-staged runs into Postgres `raw.*` as
    their RabbitMQ events arrive. Exits (and closes the connection) on
    cancellation/interrupt.

    A no-op (logs and returns immediately, opens no RabbitMQ connection)
    once `Settings.warehouse_sync_consumer_enabled` is flipped off —
    `services/waerehouse/TODO.md` Phase 4's cutover switch, letting an
    operator retire this consumer via config once `services/waerehouse`'s
    own is trusted, without deleting this module or the `warehouse-sync`
    compose service outright.
    """
    configure_logging()
    if not get_settings().warehouse_sync_consumer_enabled:
        log.info("warehouse_sync.consumer_disabled")
        return
    log.info("warehouse_sync.consumer_starting")
    try:
        await consume_landed_events(sync_landed_event)
    finally:
        await close_rabbitmq()
        log.info("warehouse_sync.consumer_stopped")
