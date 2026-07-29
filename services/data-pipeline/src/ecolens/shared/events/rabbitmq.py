"""Fire-and-forget "data ingested" event publisher.

`duckdb_store.write_historical` -- the sole write path for every
ingestion source, live or historical/backfill -- calls
`publish_data_ingested` right after a successful write.
`ecolens.warehouse.service.event_consumer` consumes these events and
triggers an incremental `WarehouseRunner` run, replacing the old
every-30-min warehouse cron with a push model.

Uses `pika` (sync, blocking), not `aio-pika`: `write_historical` is a
plain sync function called from both sync scripts and already-running
async event loops (the `/ingestion/historical` endpoints), so an async
publish would need `asyncio.run()`, which raises if called from inside
a running loop. A short blocking connect+publish+close is cheap enough
at this call frequency (a handful of times per ingestion cycle).

Best-effort by design: RabbitMQ being down must never break the
ingestion write path (the actual data is already safely in DuckDB by
the time this is called) -- every failure is caught, logged, and
swallowed, never raised. A missed event just means the next
successful write's event covers the gap too (the consumer triggers a
plain incremental WarehouseRunner run, which processes whatever is
new since last time regardless of which event woke it up).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pika
import pika.exceptions

from ecolens.config import get_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

# Kept short -- this runs inline in the ingestion write path, so a
# genuinely unreachable broker must fail fast rather than stall writes.
_CONNECT_TIMEOUT_SECONDS = 3


def publish_data_ingested(source: str, *, run_id: str, rows: int) -> None:
    """Notify the warehouse consumer that `rows` docs were written for
    `source`. Never raises -- see module docstring.
    """
    settings = get_settings()
    payload = {
        "source": source,
        "run_id": run_id,
        "rows": rows,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _publish(settings.rabbitmq_url, settings.rabbitmq_queue, payload)
    except Exception as exc:  # noqa: BLE001 - best-effort, must never break ingestion
        log.warning(
            "events.publish_failed",
            source=source,
            run_id=run_id,
            queue=settings.rabbitmq_queue,
            error=str(exc),
        )
        return
    log.info(
        "events.data_ingested_published",
        source=source,
        run_id=run_id,
        rows=rows,
        queue=settings.rabbitmq_queue,
    )


def _publish(url: str, queue: str, payload: dict[str, Any]) -> None:
    params = pika.URLParameters(url)
    params.socket_timeout = _CONNECT_TIMEOUT_SECONDS
    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        # Idempotent: whichever of the producer/consumer starts first
        # creates the queue, so neither has to assume the other is
        # already up. Durable so events survive a broker restart while
        # the consumer is briefly down.
        channel.queue_declare(queue=queue, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
        )
    finally:
        connection.close()


__all__ = ["publish_data_ingested"]
