import json

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

    async def bind(self, exchange):
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
    def __init__(self, body, timestamp=None):
        self.body = body
        self.timestamp = timestamp
        self.acked = False

    async def ack(self):
        self.acked = True


class _FakeChannel:
    def __init__(self, messages=None):
        self._messages = messages or []
        self.declared_queues: list[str] = []
        self.declared_exchanges: dict[str, _FakeExchange] = {}
        self.qos: int | None = None

    async def declare_queue(self, name, durable=True):
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
