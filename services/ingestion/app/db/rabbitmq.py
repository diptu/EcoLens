"""RabbitMQ connection + publish for the ingestion service.

`publish_landed_event` is this service's only reason to talk to
RabbitMQ -- called by `pipeline.tasks._common.standard_run` right after
a fetch is staged in DuckDB (`pipeline.duckdb_staging`). Ported from
data-pipeline's identical module, publish-side only -- this service
never consumes: `consume_landed_events`/`warehouse_sync` stay in
`data-pipeline` (see `docs/data/ingestion.md`'s service-boundary note).
`publish_training_trigger_event`/`consume_training_trigger_events`
(data-pipeline's downstream training-trigger hop) aren't part of this
service's boundary at all and aren't ported here.

One shared, lazily-connected `aio_pika.RobustConnection` per process --
robust reconnects automatically on a dropped connection, so callers
don't need their own retry logic. Same pattern as data-pipeline's
identical module.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.core.config import get_settings

_connection: AbstractRobustConnection | None = None
_connection_lock = asyncio.Lock()


async def get_rabbitmq_connection() -> AbstractRobustConnection:
    global _connection
    if _connection is None or _connection.is_closed:
        async with _connection_lock:
            if _connection is None or _connection.is_closed:
                _connection = await aio_pika.connect_robust(get_settings().rabbitmq_url)
    return _connection


async def close_rabbitmq() -> None:
    """Close the shared connection (call on service/worker shutdown)."""
    global _connection
    if _connection is not None and not _connection.is_closed:
        await _connection.close()
    _connection = None


async def publish_landed_event(
    payload: dict[str, Any], *, queue_name: str | None = None
) -> None:
    """Publish a "data staged" event — `payload` becomes the JSON message
    body `warehouse_sync.sync_landed_event` receives on the consumer side
    (still `data-pipeline`'s job, per this module's docstring).

    `queue_name` defaults to `Settings.rabbitmq_landing_queue` — pass
    `Settings.rabbitmq_landing_queue_shadow` for a Phase 4 shadow run
    (`pipeline.tasks._common.standard_run`'s `triggered_by="shadow"`
    path) so the real consumer never picks it up.

    Persistent delivery mode + a durable queue: a message survives a
    RabbitMQ restart between publish and consume (matches `meta.
    _ingest_log`'s own durability expectations — a "staged" row shouldn't
    be able to silently vanish before it's synced).
    """
    settings = get_settings()
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    try:
        queue = await channel.declare_queue(
            queue_name or settings.rabbitmq_landing_queue, durable=True
        )
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=queue.name,
        )
    finally:
        await channel.close()
