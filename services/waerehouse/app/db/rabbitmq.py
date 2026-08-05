"""RabbitMQ consumer framework for the event-driven warehousing pipeline
(`overview.md` §2, README Phase 1's "robust asynchronous RabbitMQ
consumer... automatic reconnections, dead-letter exchanges (DLX), and
manual acknowledgment handling").

Consume-only — the mirror image of `services/ingestion`'s publish-only
`app.db.rabbitmq`. `consume_landed_events` reads `Settings.
rabbitmq_landing_queue` (`"ecolens.landing"`), the exact queue ingestion's
`publish_landed_event` writes to — the queue *name* is the one real
coupling point between the two services.

**DLX design note**: `ecolens.landing` already exists live, declared
plain by ingestion (`durable=True`, no `arguments`) — confirmed directly
against the real broker (`GET /api/queues/%2f/ecolens.landing` ->
`"arguments": {}`) before writing this. Redeclaring that same queue here
with an `x-dead-letter-exchange` argument would raise `PRECONDITION_
FAILED` (RabbitMQ rejects a re-declare whose arguments don't match the
queue's existing ones) — so native queue-level DLX isn't an option
without either changing ingestion's own declaration (a different,
already-live service) or deleting/recreating the queue (destructive,
risks dropping in-flight messages). Instead, dead-lettering is handled
at the **application level**: `_declare_dlx_topology` declares a
*separate*, fresh fanout exchange (`rabbitmq_landing_dlx`) + queue
(`rabbitmq_landing_dlq`) that never collides with anything ingestion
touches; `consume_landed_events` explicitly publishes a failed message's
body (plus the error) there before acking the original off the main
queue — same practical outcome (failed messages land in an inspectable
queue, the main queue keeps flowing, nothing loops forever), without
touching `ecolens.landing`'s own existing topology at all.

One shared, lazily-connected `aio_pika.RobustConnection` per process
(`get_rabbitmq_connection`) — robust reconnects automatically on a
dropped connection, so callers don't need their own retry logic.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import consume_failures_total, queue_message_age_seconds

log = get_logger(__name__)

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


async def _declare_dlx_topology(
    channel: aio_pika.abc.AbstractChannel,
) -> aio_pika.abc.AbstractExchange:
    """Declares (idempotently) this service's own dead-letter fanout
    exchange + queue and binds them. Returns the exchange to publish
    failed messages to. Safe to call from multiple processes concurrently
    — declaring is a no-op once it already exists with matching
    arguments, same pattern `data-pipeline`'s training-trigger DLX uses.
    """
    settings = get_settings()
    dlx = await channel.declare_exchange(
        settings.rabbitmq_landing_dlx, aio_pika.ExchangeType.FANOUT, durable=True
    )
    dlq = await channel.declare_queue(settings.rabbitmq_landing_dlq, durable=True)
    await dlq.bind(dlx)
    return dlx


async def _publish_to_dlq(
    channel: aio_pika.abc.AbstractChannel,
    dlx: aio_pika.abc.AbstractExchange,
    raw_body: bytes,
    error: str,
) -> None:
    await dlx.publish(
        aio_pika.Message(
            body=raw_body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
            headers={"x-death-reason": error[:1000]},
        ),
        routing_key="",
    )


async def consume_landed_events(
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Consume `Settings.rabbitmq_landing_queue` forever, calling
    `handler(payload)` for each message.

    Manual ack/nack (`prefetch_count=1` — one in-flight sync at a time,
    so a slow Postgres load doesn't let a backlog pile up unacked in
    memory): on a clean `handler` return, the message is acked. On any
    exception, the raw message body + the error is published to this
    service's own DLQ (see module docstring for why that's application-
    level rather than a native queue-argument DLX here), then the
    original message is **also acked** — not nacked-and-requeued, which
    would loop the same bad message forever. The DLQ is the durable
    record for a human to inspect/manually replay, not RabbitMQ's own
    redelivery mechanism.

    One bad message must never stop the rest of the queue from being
    consumed — the `try`/`except` wraps each message individually, same
    reasoning `data-pipeline`'s identical consumer documents.
    """
    settings = get_settings()
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    dlx = await _declare_dlx_topology(channel)
    queue = await channel.declare_queue(settings.rabbitmq_landing_queue, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            started = time.monotonic()
            if message.timestamp is not None:
                queue_message_age_seconds.observe(
                    max(0.0, time.time() - message.timestamp.timestamp())
                )
            try:
                payload = json.loads(message.body)
                await handler(payload)
                await message.ack()
            except Exception as exc:  # noqa: BLE001 - one bad message must not kill the consumer
                source = None
                try:
                    source = json.loads(message.body).get("source")
                except Exception:  # noqa: BLE001 - body may not even be valid JSON
                    pass
                consume_failures_total.labels(source=source or "unknown").inc()
                log.error(
                    "warehouse.consume_failed",
                    error=str(exc),
                    source=source,
                    elapsed=time.monotonic() - started,
                )
                await _publish_to_dlq(channel, dlx, message.body, str(exc))
                await message.ack()
