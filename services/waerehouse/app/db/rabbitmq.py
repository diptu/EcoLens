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
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from opentelemetry import context as otel_context
from opentelemetry.propagate import extract

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

    `extract(message.headers)`/`otel_context.attach` (`TODO.md`
    Observability Phase 1's "Distributed Trace Propagation"): a real
    W3C `traceparent` header, written by `services/ingestion`'s
    `db.rabbitmq.publish_landed_event` from *its* own `ingestion.
    standard_run` span, becomes the *current* context for the duration
    of this one `handler(payload)` call -- so `consumers.landed_events.
    sync_landed_event`'s own `tracer.start_as_current_span(...)`
    automatically parents onto it, giving a real two-service linked
    trace instead of two spans that just happen to run near each other
    in time. A message with no header (tracing disabled on the
    publisher, or a message from before this existed) extracts to an
    empty context -- `sync_landed_event` still starts its own span, just
    unparented, same as it always did before this existed.
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
                ctx = extract(dict(message.headers or {}))
                token = otel_context.attach(ctx)
                try:
                    await handler(payload)
                finally:
                    otel_context.detach(token)
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


async def _declare_training_trigger_topology(
    channel: aio_pika.abc.AbstractChannel,
) -> aio_pika.abc.AbstractExchange:
    """Declares (idempotently) the training-trigger exchange/DLX/DLQ and
    binds them -- publish-side only here (this service never consumes
    its own training-trigger events; `forecast-api`'s `training_worker`
    does). Ported from data-pipeline's identical
    `_declare_training_trigger_topology`, same topology/names so either
    side connecting first is fine. Returns the exchange to publish to.
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
    return exchange


async def publish_training_trigger_event(payload: dict[str, Any]) -> None:
    """Publish a "warehouse transform completed, incremental training
    may run" event -- `payload` becomes the JSON message body
    `forecast-api`'s `training_worker.handle_training_trigger` receives
    on the consumer side. Ported from data-pipeline's identical
    function; the real work (building the payload) moved to
    `app.service.training_trigger.publish_training_trigger`, this is
    just the wire step.

    Persistent delivery mode + a durable queue: a message survives a
    RabbitMQ restart between publish and consume, same durability
    rationale ingestion's `publish_landed_event` documents for its own
    queue.
    """
    settings = get_settings()
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    try:
        exchange = await _declare_training_trigger_topology(channel)
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


async def run_consumer_forever(
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """`consume_landed_events(handler)`, but exits cleanly on SIGTERM
    (what `docker stop`/an orchestrator sends on shutdown, not SIGINT/
    Ctrl+C) instead of running until the container's stop grace period
    elapses and SIGKILL ends it mid-anything. `cli.py`'s `consume`
    command is the only real caller; split out here (not left inline in
    the CLI command) so the shutdown logic is testable without actually
    sending a process a signal.

    **Not a data-safety fix** — `consume_landed_events` only ever acks a
    message *after* its handler succeeds, so a message in flight when
    killed (SIGTERM *or* a bare SIGKILL, same as before this existed) is
    simply redelivered by RabbitMQ on reconnect either way, landing
    through the same idempotent `ON CONFLICT DO NOTHING` path either
    time. This is about exiting promptly with a clean log line and a
    closed connection instead of relying on SIGKILL as the only way this
    process ever stops.

    `loop.add_signal_handler` isn't implemented on Windows' default
    asyncio event loop — falls back to no-op there (Ctrl+C/
    `KeyboardInterrupt` still works for local dev); every real deployment
    of this service runs in a Linux container, where it works.
    """
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(consume_landed_events(handler))

    def _handle_sigterm() -> None:
        task.cancel()

    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
    except NotImplementedError:
        pass

    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        await close_rabbitmq()
