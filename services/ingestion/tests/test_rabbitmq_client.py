import json

import pytest

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


class _FakeConnection:
    def __init__(self, is_closed: bool = False):
        self.is_closed = is_closed

    async def close(self):
        self.is_closed = True


async def test_get_rabbitmq_connection_reuses_a_live_connection(monkeypatch):
    fake = _FakeConnection()

    async def fake_connect_robust(url):
        return fake

    monkeypatch.setattr(rabbitmq_client.aio_pika, "connect_robust", fake_connect_robust)

    first = await rabbitmq_client.get_rabbitmq_connection()
    second = await rabbitmq_client.get_rabbitmq_connection()

    assert first is fake
    assert second is fake


async def test_get_rabbitmq_connection_reconnects_once_closed(monkeypatch):
    calls = []

    async def fake_connect_robust(url):
        conn = _FakeConnection()
        calls.append(conn)
        return conn

    monkeypatch.setattr(rabbitmq_client.aio_pika, "connect_robust", fake_connect_robust)

    first = await rabbitmq_client.get_rabbitmq_connection()
    first.is_closed = True
    second = await rabbitmq_client.get_rabbitmq_connection()

    assert len(calls) == 2
    assert second is not first


async def test_close_rabbitmq_closes_and_clears_the_cached_connection():
    fake = _FakeConnection()
    rabbitmq_client._connection = fake

    await rabbitmq_client.close_rabbitmq()

    assert fake.is_closed is True
    assert rabbitmq_client._connection is None


async def test_close_rabbitmq_is_a_noop_when_nothing_is_connected():
    await rabbitmq_client.close_rabbitmq()  # should not raise


class _FakeQueue:
    def __init__(self, name):
        self.name = name


class _FakeExchange:
    def __init__(self):
        self.published: list[tuple[bytes, str]] = []

    async def publish(self, message, routing_key):
        self.published.append((message.body, routing_key))


class _FakePublishChannel:
    def __init__(self):
        self.default_exchange = _FakeExchange()
        self.declared_queues: list[str] = []
        self.closed = False

    async def declare_queue(self, name, durable=True):
        self.declared_queues.append(name)
        return _FakeQueue(name)

    async def close(self):
        self.closed = True


class _FakePublishConnection:
    def __init__(self):
        self.is_closed = False
        self.channel_obj = _FakePublishChannel()

    async def channel(self):
        return self.channel_obj

    async def close(self):
        self.is_closed = True


async def test_publish_landed_event_publishes_json_to_the_configured_queue(monkeypatch):
    fake_connection = _FakePublishConnection()

    async def fake_get_connection():
        return fake_connection

    monkeypatch.setattr(rabbitmq_client, "get_rabbitmq_connection", fake_get_connection)

    payload = {"run_id": "abc", "source": "bom", "rows": 10}
    await rabbitmq_client.publish_landed_event(payload)

    channel = fake_connection.channel_obj
    assert channel.declared_queues == ["ecolens.landing"]
    body, routing_key = channel.default_exchange.published[0]
    assert json.loads(body) == payload
    assert routing_key == "ecolens.landing"
    assert channel.closed is True


async def test_publish_landed_event_honours_a_queue_name_override(monkeypatch):
    """Phase 4's "Execute Shadow Runs" -- `standard_run` passes the shadow
    queue name here for `triggered_by="shadow"` runs."""
    fake_connection = _FakePublishConnection()

    async def fake_get_connection():
        return fake_connection

    monkeypatch.setattr(rabbitmq_client, "get_rabbitmq_connection", fake_get_connection)

    payload = {"run_id": "abc", "source": "bom", "rows": 10}
    await rabbitmq_client.publish_landed_event(
        payload, queue_name="ecolens.landing.shadow"
    )

    channel = fake_connection.channel_obj
    assert channel.declared_queues == ["ecolens.landing.shadow"]
    _, routing_key = channel.default_exchange.published[0]
    assert routing_key == "ecolens.landing.shadow"
