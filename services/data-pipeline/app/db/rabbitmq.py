"""RabbitMQ client for decoupling ingestion from warehousing
(`overview.md` §2 Event-Driven Warehousing), and warehousing from
incremental training (`TODO.md`'s "Event-Driven Pipeline Trigger for
Online/Incremental Model Training").

`publish_landed_event` is called by `pipeline.tasks._common.standard_run`
right after a fetch is staged in DuckDB (`pipeline.duckdb_staging`).
`consume_landed_events` is the long-running loop `pipeline.warehouse_sync`
/ the `ecolens-pipeline worker` CLI command / the `warehouse-sync`
docker-compose service runs to pick those events back up and sync the
staged data into Postgres `raw.*`.

`publish_training_trigger_event`/`consume_training_trigger_events` are the
same producer/consumer shape, one hop further downstream: `pipeline.flows`'
`daily-demand` Prefect flow publishes once a dbt build actually succeeds,
and `app.service.training_worker` (the `ecolens-pipeline train-worker` CLI
command / `train-worker` docker-compose service) consumes them to run an
incremental (warm-started) training pass, `ml.incremental`. Unlike the
landing queue (`channel.default_exchange`, no DLX -- a failed sync just
gets retried from the DuckDB file still on disk), this one has a real
topology: a topic exchange, a queue whose `x-dead-letter-exchange`
argument points at a fanout DLX, and a DLQ bound to that DLX -- a message
that a handler raises on (malformed payload, no warm-startable model
version, etc.) gets dead-lettered instead of disappearing, since there's
no on-disk recovery artifact for a training-trigger event the way there
is for a landing one.

One shared, lazily-connected `aio_pika.RobustConnection` per process
(`get_rabbitmq_connection`) — robust reconnects automatically on a
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


async def publish_landed_event(payload: dict[str, Any]) -> None:
    """Publish a "data staged" event — `payload` becomes the JSON message
    body `warehouse_sync.sync_landed_event` receives on the consumer side.

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
            settings.rabbitmq_landing_queue, durable=True
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


async def consume_landed_events(
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Consume `rabbitmq_landing_queue` forever, calling `handler(payload)`
    for each message.

    `message.process()` acks on a clean return from `handler` and nacks
    (without requeueing) on an exception — a failed sync doesn't loop
    forever redelivering the same message; it's recorded as `sync_failed`
    in `meta._ingest_log` by the handler (`warehouse_sync.
    sync_landed_event`) and the DuckDB file stays on disk as the recovery
    artifact for a manual retry, same role `pipeline/tasks/task.md`'s old
    S3-replay playbook served.

    `prefetch_count=1` — one in-flight sync at a time, so a slow Postgres
    load doesn't let a backlog of messages pile up unacked in memory.
    """
    settings = get_settings()
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    queue = await channel.declare_queue(settings.rabbitmq_landing_queue, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(requeue=False):
                payload = json.loads(message.body)
                await handler(payload)


async def _declare_training_trigger_topology(
    channel: aio_pika.abc.AbstractChannel,
) -> tuple[aio_pika.abc.AbstractExchange, aio_pika.abc.AbstractQueue]:
    """Declares (idempotently) the training-trigger exchange/queue/DLX/DLQ
    and binds them, per this module's docstring. Shared by publish and
    consume so the topology is defined in exactly one place — either side
    connecting first is fine, declaring is a no-op once it already exists
    with matching arguments.

    Returns `(exchange, queue)` — the exchange to publish to, the queue to
    consume from.
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
    run" event — `payload` becomes the JSON message body
    `training_worker.handle_training_trigger` receives on the consumer
    side (batch metadata: timestamp window, dataset reference, anomaly
    summary — see `pipeline.flows.publish_training_trigger`, the caller).

    Persistent delivery mode + a durable queue, same durability rationale
    as `publish_landed_event`.
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

    Same ack/nack shape as `consume_landed_events`: `message.process()`
    acks on a clean return, nacks (without requeueing) on any exception
    (including a malformed `json.loads`) — but because the queue's
    `x-dead-letter-exchange` argument points at `rabbitmq_training_dlx`
    (`_declare_training_trigger_topology`), a nack doesn't just drop the
    message, it republishes it to the DLX, landing in
    `rabbitmq_training_trigger_dlq` for inspection/manual replay — the
    real DLX policy `TODO.md`'s item 2 asks for.

    `prefetch_count=1` — one incremental training run at a time; a second
    trigger event arriving mid-training waits rather than kicking off a
    concurrent run against the same model name.
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
