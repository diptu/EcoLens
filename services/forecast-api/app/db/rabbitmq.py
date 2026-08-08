"""RabbitMQ client for the training-trigger topology -- ported from
data-pipeline's identical `app/db/rabbitmq.py`, training-trigger half
only (`publish_landed_event`/`consume_landed_events`, the ingestion-to-
warehouse hop, stay out of scope for this service; see `services/
ingestion`'s and `services/waerehouse`'s own copies for those).

Both halves live here, unlike `services/waerehouse`'s publish-only copy:
`publish_training_trigger_event` backs `POST /v1/model/train`'s manual
trigger (`app.service.model.actions.trigger_training`), and
`consume_training_trigger_events` is what `app.service.training_worker`
(the `train-worker` docker-compose service / `ecolens-forecast
train-worker` CLI command) runs forever to pick up both the automatic
(post-dbt-build, published by `services/waerehouse`) and manual triggers
-- same queue, either publisher.

One shared, lazily-connected `aio_pika.RobustConnection` per process
(`get_rabbitmq_connection`) -- robust reconnects automatically on a
dropped connection, so callers don't need their own retry logic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.core.config import get_settings
from app.core.logging import get_logger

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


async def _declare_training_trigger_topology(
    channel: aio_pika.abc.AbstractChannel,
) -> tuple[aio_pika.abc.AbstractExchange, aio_pika.abc.AbstractQueue]:
    """Declares (idempotently) the training-trigger exchange/queue/DLX/DLQ
    and binds them, per this module's docstring. Shared by publish and
    consume so the topology is defined in exactly one place -- either
    side (this service or `services/waerehouse`'s publish-only copy)
    connecting first is fine, declaring is a no-op once it already
    exists with matching arguments.

    Returns `(exchange, queue)` -- the exchange to publish to, the queue
    to consume from.
    """
    settings = get_settings()
    dlx = await channel.declare_exchange(
        settings.rabbitmq_training_dlx, aio_pika.ExchangeType.FANOUT, durable=True
    )
    dlq = await channel.declare_queue(
        settings.rabbitmq_training_trigger_dlq, durable=True
    )
    await dlq.bind(dlx)

    exchange = await channel.declare_exchange(
        settings.rabbitmq_training_exchange, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(
        settings.rabbitmq_training_trigger_queue,
        durable=True,
        arguments={"x-dead-letter-exchange": settings.rabbitmq_training_dlx},
    )
    await queue.bind(exchange, routing_key=settings.rabbitmq_training_routing_key)
    return exchange, queue


async def publish_training_trigger_event(payload: dict[str, Any]) -> None:
    """Publish a "warehouse transform completed, incremental training may
    run" event -- `payload` becomes the JSON message body
    `training_worker.handle_training_trigger` receives on the consumer
    side. `app.service.model.actions.trigger_training`'s manual
    `POST /v1/model/train` path is this service's only caller;
    `services/waerehouse`'s `dbt.training_trigger.publish_training_trigger`
    fires the automatic (post-dbt-build) path from its own identical
    copy of this function.

    Persistent delivery mode + a durable queue, same durability
    rationale ingestion's `publish_landed_event` documents for its own
    queue.
    """
    settings = get_settings()
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    try:
        exchange, _ = await _declare_training_trigger_topology(channel)
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=settings.rabbitmq_training_routing_key,
        )
    finally:
        await channel.close()


async def consume_training_trigger_events(
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Consume `rabbitmq_training_trigger_queue` forever, calling
    `handler(payload)` for each message.

    `message.process()` acks on a clean return, nacks (without
    requeueing) on any exception (including a malformed `json.loads`) --
    but because the queue's `x-dead-letter-exchange` argument points at
    `rabbitmq_training_dlx` (`_declare_training_trigger_topology`), a
    nack doesn't just drop the message, it republishes it to the DLX,
    landing in `rabbitmq_training_trigger_dlq` for inspection/manual
    replay.

    `prefetch_count=1` -- one incremental training run at a time; a
    second trigger event arriving mid-training waits rather than
    kicking off a concurrent run against the same model name.
    """
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    _, queue = await _declare_training_trigger_topology(channel)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(requeue=False):
                payload = json.loads(message.body)
                await handler(payload)
