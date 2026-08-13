import asyncio
import json
import os
import signal
import sys

import pytest

from app.core.metrics import consume_failures_total
from app.db import rabbitmq as rabbitmq_client

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_connection():
    rabbitmq_client._connection = None
    yield
    rabbitmq_client._connection = None


class _FakeExchange:
    def __init__(self, name):
        self.name = name
        self.published: list[tuple[bytes, str, dict]] = []

    async def publish(self, message, routing_key):
        self.published.append((message.body, routing_key, message.headers or {}))


class _FakeQueue:
    def __init__(self, name, messages=None):
        self.name = name
        self._messages = messages or []

    def iterator(self):
        return _FakeQueueIterator(self._messages)

    async def bind(self, exchange, routing_key=None):
        pass


class _FakeQueueIterator:
    def __init__(self, messages):
        self._messages = messages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for message in self._messages:
            yield message


class _FakeMessage:
    def __init__(self, body, timestamp=None, headers=None):
        self.body = body
        self.timestamp = timestamp
        self.headers = headers
        self.acked = False

    async def ack(self):
        self.acked = True


class _FakeChannel:
    def __init__(self, messages=None):
        self._messages = messages or []
        self.declared_queues: list[str] = []
        self.declared_exchanges: dict[str, _FakeExchange] = {}
        self.qos: int | None = None

    async def declare_queue(self, name, durable=True, arguments=None):
        self.declared_queues.append(name)
        return _FakeQueue(name, self._messages)

    async def declare_exchange(self, name, exchange_type, durable=True):
        exchange = _FakeExchange(name)
        self.declared_exchanges[name] = exchange
        return exchange

    async def set_qos(self, prefetch_count):
        self.qos = prefetch_count

    async def close(self):
        pass


class _FakeConnection:
    def __init__(self, messages=None):
        self.is_closed = False
        self.channel_obj = _FakeChannel(messages)

    async def channel(self):
        return self.channel_obj

    async def close(self):
        self.is_closed = True


def _wire(monkeypatch, messages):
    connection = _FakeConnection(messages)

    async def fake_get_connection():
        return connection

    monkeypatch.setattr(rabbitmq_client, "get_rabbitmq_connection", fake_get_connection)
    return connection


async def test_consume_landed_events_calls_handler_and_acks_on_success(monkeypatch):
    messages = [
        _FakeMessage(json.dumps({"run_id": "1", "source": "bom"}).encode()),
        _FakeMessage(json.dumps({"run_id": "2", "source": "oe"}).encode()),
    ]
    connection = _wire(monkeypatch, messages)

    seen = []

    async def handler(payload):
        seen.append(payload)

    await rabbitmq_client.consume_landed_events(handler)

    assert seen == [{"run_id": "1", "source": "bom"}, {"run_id": "2", "source": "oe"}]
    assert all(m.acked for m in messages)
    assert connection.channel_obj.qos == 1


async def test_consume_landed_events_declares_the_dlx_topology(monkeypatch):
    connection = _wire(monkeypatch, [])

    await rabbitmq_client.consume_landed_events(lambda payload: None)

    channel = connection.channel_obj
    assert "ecolens.landing.dlx" in channel.declared_exchanges
    assert "ecolens.landing.dlq" in channel.declared_queues
    assert "ecolens.landing" in channel.declared_queues


async def test_consume_landed_events_links_the_handler_to_the_publishers_span(
    monkeypatch,
):
    """`TODO.md` Observability Phase 1's "Distributed Trace Propagation"
    -- a message carrying `services/ingestion`'s real W3C `traceparent`
    header must make that trace *current* for the duration of the
    `handler(payload)` call, so `sync_landed_event`'s own span parents
    onto it instead of starting an unrelated trace."""
    from opentelemetry import trace
    from opentelemetry.propagate import inject
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    headers: dict = {}
    with tracer.start_as_current_span("ingestion.standard_run") as publisher_span:
        expected_trace_id = publisher_span.get_span_context().trace_id
        inject(headers)

    message = _FakeMessage(
        json.dumps({"run_id": "1", "source": "bom"}).encode(), headers=headers
    )
    _wire(monkeypatch, [message])

    seen_trace_ids = []

    async def handler(payload):
        seen_trace_ids.append(trace.get_current_span().get_span_context().trace_id)

    await rabbitmq_client.consume_landed_events(handler)

    assert seen_trace_ids == [expected_trace_id]


async def test_consume_landed_events_tolerates_a_message_with_no_headers(monkeypatch):
    """A message published before this existed, or with tracing disabled
    on the publisher (`headers=None`, not an empty dict) -- extraction
    must not raise, and the handler still runs and acks normally."""
    message = _FakeMessage(
        json.dumps({"run_id": "1", "source": "bom"}).encode(), headers=None
    )
    _wire(monkeypatch, [message])

    seen = []

    async def handler(payload):
        seen.append(payload)

    await rabbitmq_client.consume_landed_events(handler)

    assert seen == [{"run_id": "1", "source": "bom"}]
    assert message.acked is True


async def test_a_failing_handler_publishes_to_the_dlq_and_still_acks(monkeypatch):
    """One bad message must never stop the rest of the queue from being
    consumed, and must never loop forever redelivering -- it's acked off
    the main queue after being copied to the DLQ for inspection."""
    body = json.dumps({"run_id": "1", "source": "bom"}).encode()
    good_body = json.dumps({"run_id": "2", "source": "oe"}).encode()
    bad_message = _FakeMessage(body)
    good_message = _FakeMessage(good_body)
    connection = _wire(monkeypatch, [bad_message, good_message])

    seen = []

    async def handler(payload):
        if payload["run_id"] == "1":
            raise RuntimeError("duckdb file corrupted")
        seen.append(payload)

    await rabbitmq_client.consume_landed_events(handler)

    assert seen == [{"run_id": "2", "source": "oe"}]
    assert bad_message.acked is True
    assert good_message.acked is True

    dlx = connection.channel_obj.declared_exchanges["ecolens.landing.dlx"]
    assert len(dlx.published) == 1
    published_body, routing_key, headers = dlx.published[0]
    assert published_body == body
    assert "duckdb file corrupted" in headers["x-death-reason"]


async def test_a_failing_handler_increments_the_failure_metric(monkeypatch):
    before = consume_failures_total.labels(source="bom")._value.get()
    connection = _wire(  # noqa: F841 - wiring side effect, connection itself unused
        monkeypatch, [_FakeMessage(json.dumps({"source": "bom"}).encode())]
    )

    async def handler(payload):
        raise RuntimeError("boom")

    await rabbitmq_client.consume_landed_events(handler)

    after = consume_failures_total.labels(source="bom")._value.get()
    assert after == before + 1


async def test_a_message_with_unparseable_json_is_dead_lettered_not_fatal(monkeypatch):
    bad_message = _FakeMessage(b"not valid json{{{")
    connection = _wire(monkeypatch, [bad_message])

    await rabbitmq_client.consume_landed_events(lambda payload: None)

    assert bad_message.acked is True
    dlx = connection.channel_obj.declared_exchanges["ecolens.landing.dlx"]
    assert len(dlx.published) == 1


async def test_close_rabbitmq_closes_and_clears_the_cached_connection():
    connection = _FakeConnection()
    rabbitmq_client._connection = connection

    await rabbitmq_client.close_rabbitmq()

    assert connection.is_closed is True
    assert rabbitmq_client._connection is None


async def test_close_rabbitmq_is_a_noop_when_nothing_is_connected():
    await rabbitmq_client.close_rabbitmq()  # should not raise


# ── run_consumer_forever (graceful SIGTERM shutdown) ────────────────────


async def test_run_consumer_forever_closes_the_connection_on_normal_completion(
    monkeypatch,
):
    """No signal involved -- the queue just runs out of messages (as the
    fakes above always do) and `consume_landed_events` returns on its
    own. `run_consumer_forever` must still close the connection, same as
    the SIGTERM path below."""
    connection = _wire(monkeypatch, [_FakeMessage(json.dumps({"source": "bom"}).encode())])
    # `close_rabbitmq()` (called by `run_consumer_forever`'s own `finally`)
    # closes the module-level cached `_connection`, not just whatever
    # `get_rabbitmq_connection` happens to return -- `_wire`'s fake
    # doesn't populate that cache (existing `consume_landed_events`-only
    # tests never call `close_rabbitmq`, so never needed to); set it
    # explicitly here, same as `test_close_rabbitmq_closes_and_clears_
    # the_cached_connection` already does.
    rabbitmq_client._connection = connection

    async def handler(payload):
        pass

    await rabbitmq_client.run_consumer_forever(handler)

    assert connection.is_closed is True


class _FakeHangingQueueIterator:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        await asyncio.Event().wait()
        yield  # pragma: no cover -- unreachable; makes this a real async generator


class _FakeHangingQueue:
    def iterator(self):
        return _FakeHangingQueueIterator()

    async def bind(self, exchange):
        pass


class _FakeHangingChannel(_FakeChannel):
    """Like `_FakeChannel`, except the main landing queue never yields a
    message and never finishes -- `consume_landed_events`'s `async for`
    blocks forever on it, same as the real thing does between messages,
    so cancelling it is the only way it ever returns."""

    async def declare_queue(self, name, durable=True):
        self.declared_queues.append(name)
        if name == rabbitmq_client.get_settings().rabbitmq_landing_queue:
            return _FakeHangingQueue()
        return _FakeQueue(name, [])


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="loop.add_signal_handler isn't implemented on Windows' asyncio "
    "event loop -- run_consumer_forever falls back to a no-op there by "
    "design (see its own docstring); every real deployment is Linux.",
)
async def test_run_consumer_forever_exits_cleanly_on_sigterm(monkeypatch):
    """The real integration case: a genuine SIGTERM sent to this process
    (what `docker stop` sends) while the consumer is blocked waiting on
    the queue must cancel the consume loop and close the connection,
    instead of hanging until something more forceful (SIGKILL) ends it.
    """
    connection = _FakeConnection()
    connection.channel_obj = _FakeHangingChannel()

    async def fake_get_connection():
        return connection

    monkeypatch.setattr(rabbitmq_client, "get_rabbitmq_connection", fake_get_connection)
    rabbitmq_client._connection = connection  # see the sibling test's own note on why

    async def _send_sigterm_shortly():
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGTERM)

    sender = asyncio.ensure_future(_send_sigterm_shortly())
    await asyncio.wait_for(
        rabbitmq_client.run_consumer_forever(lambda payload: None), timeout=5
    )
    await sender

    assert connection.is_closed is True


class TestPublishTrainingTriggerEvent:
    """`publish_training_trigger_event` -- the publish-only half of the
    training-trigger topology (`forecast-api`'s `training_worker`
    consumes what this publishes)."""

    async def test_publishes_to_the_training_exchange_with_the_routing_key(
        self, monkeypatch
    ):
        connection = _wire(monkeypatch, [])
        payload = {"event": "warehouse.transform.completed", "architecture": "lstm"}

        await rabbitmq_client.publish_training_trigger_event(payload)

        channel = connection.channel_obj
        exchange = channel.declared_exchanges["forecasting.training"]
        assert len(exchange.published) == 1
        body, routing_key, _headers = exchange.published[0]
        assert json.loads(body) == payload
        assert routing_key == "training.trigger"

    async def test_declares_the_training_dlx_topology(self, monkeypatch):
        connection = _wire(monkeypatch, [])

        await rabbitmq_client.publish_training_trigger_event({"architecture": "lstm"})

        channel = connection.channel_obj
        assert "forecasting.training.dlx" in channel.declared_exchanges
        assert "forecasting.training.trigger.dlq" in channel.declared_queues
        assert "forecasting.training.trigger" in channel.declared_queues
