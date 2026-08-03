import json

import aio_pika
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


class _FakeQueue:
    def __init__(self, name):
        self.name = name


class _FakeExchange:
    def __init__(self):
        self.published: list[tuple[bytes, str]] = []

    async def publish(self, message, routing_key):
        self.published.append((message.body, routing_key))


class _FakeChannel:
    def __init__(self):
        self.default_exchange = _FakeExchange()
        self.declared_queues: list[str] = []
        self.closed = False
        self.qos: int | None = None

    async def declare_queue(self, name, durable=True):
        self.declared_queues.append(name)
        return _FakeQueue(name)

    async def set_qos(self, prefetch_count):
        self.qos = prefetch_count

    async def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self):
        self.is_closed = False
        self.channel_obj = _FakeChannel()

    async def channel(self):
        return self.channel_obj

    async def close(self):
        self.is_closed = True


async def test_publish_landed_event_publishes_json_to_the_configured_queue(monkeypatch):
    fake_connection = _FakeConnection()

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


async def test_close_rabbitmq_closes_and_clears_the_cached_connection(monkeypatch):
    fake_connection = _FakeConnection()
    rabbitmq_client._connection = fake_connection

    await rabbitmq_client.close_rabbitmq()

    assert fake_connection.is_closed is True
    assert rabbitmq_client._connection is None


async def test_close_rabbitmq_is_a_noop_when_nothing_is_connected():
    await rabbitmq_client.close_rabbitmq()  # should not raise


async def test_consume_landed_events_calls_handler_for_each_message():
    class _FakeMessage:
        def __init__(self, body):
            self.body = body
            self.processed = False

        def process(self, requeue=False):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

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

    class _ConsumeFakeQueue:
        def __init__(self, messages):
            self._messages = messages

        def iterator(self):
            return _FakeQueueIterator(self._messages)

    class _ConsumeFakeChannel(_FakeChannel):
        def __init__(self, messages):
            super().__init__()
            self._messages = messages

        async def declare_queue(self, name, durable=True):
            await super().declare_queue(name, durable=durable)
            return _ConsumeFakeQueue(self._messages)

    messages = [
        _FakeMessage(json.dumps({"run_id": "1"}).encode()),
        _FakeMessage(json.dumps({"run_id": "2"}).encode()),
    ]

    class _ConsumeFakeConnection(_FakeConnection):
        def __init__(self, messages):
            super().__init__()
            self.channel_obj = _ConsumeFakeChannel(messages)

    connection = _ConsumeFakeConnection(messages)

    async def fake_get_connection():
        return connection

    import app.db.rabbitmq as mod

    orig = mod.get_rabbitmq_connection
    mod.get_rabbitmq_connection = fake_get_connection
    try:
        seen = []

        async def handler(payload):
            seen.append(payload)

        await mod.consume_landed_events(handler)

        assert seen == [{"run_id": "1"}, {"run_id": "2"}]
        assert connection.channel_obj.qos == 1
    finally:
        mod.get_rabbitmq_connection = orig


# ── training-trigger topology (exchange + DLX + DLQ + main queue) ─────────


class _TrainFakeExchange:
    def __init__(self, name, exchange_type=None):
        self.name = name
        self.exchange_type = exchange_type
        self.published: list[tuple[bytes, str]] = []

    async def publish(self, message, routing_key):
        self.published.append((message.body, routing_key))


class _TrainFakeQueue:
    def __init__(self, name, arguments=None):
        self.name = name
        self.arguments = arguments
        self.bound: list[tuple[str, str | None]] = []

    async def bind(self, exchange, routing_key=None):
        self.bound.append((exchange.name, routing_key))


class _TrainFakeChannel:
    def __init__(self):
        self.exchanges: dict[str, _TrainFakeExchange] = {}
        self.queues: dict[str, _TrainFakeQueue] = {}
        self.closed = False
        self.qos: int | None = None

    async def declare_exchange(self, name, exchange_type, durable=True):
        return self.exchanges.setdefault(name, _TrainFakeExchange(name, exchange_type))

    async def declare_queue(self, name, durable=True, arguments=None):
        queue = self.queues.setdefault(name, _TrainFakeQueue(name, arguments))
        queue.arguments = arguments
        return queue

    async def set_qos(self, prefetch_count):
        self.qos = prefetch_count

    async def close(self):
        self.closed = True


class _TrainFakeConnection:
    def __init__(self):
        self.is_closed = False
        self.channel_obj = _TrainFakeChannel()

    async def channel(self):
        return self.channel_obj

    async def close(self):
        self.is_closed = True


async def test_publish_training_trigger_event_declares_dlx_topology_and_publishes(
    monkeypatch,
):
    fake_connection = _TrainFakeConnection()

    async def fake_get_connection():
        return fake_connection

    monkeypatch.setattr(rabbitmq_client, "get_rabbitmq_connection", fake_get_connection)

    payload = {"event": "warehouse.transform.completed", "regions": ["NSW1"]}
    await rabbitmq_client.publish_training_trigger_event(payload)

    channel = fake_connection.channel_obj
    assert set(channel.exchanges) == {
        "forecasting.training",
        "forecasting.training.dlx",
    }
    assert channel.exchanges["forecasting.training.dlx"].exchange_type == (
        aio_pika.ExchangeType.FANOUT
    )
    assert (
        channel.exchanges["forecasting.training"].exchange_type
        == aio_pika.ExchangeType.TOPIC
    )

    dlq = channel.queues["forecasting.training.trigger.dlq"]
    assert dlq.bound == [("forecasting.training.dlx", None)]

    main_queue = channel.queues["forecasting.training.trigger"]
    assert main_queue.arguments == {
        "x-dead-letter-exchange": "forecasting.training.dlx"
    }
    assert main_queue.bound == [("forecasting.training", "training.trigger")]

    exchange = channel.exchanges["forecasting.training"]
    body, routing_key = exchange.published[0]
    assert json.loads(body) == payload
    assert routing_key == "training.trigger"
    assert channel.closed is True


async def test_consume_training_trigger_events_processes_messages_and_sets_qos(
    monkeypatch,
):
    class _FakeMessage:
        def __init__(self, body):
            self.body = body

        def process(self, requeue=False):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

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

    messages = [
        _FakeMessage(json.dumps({"event": "a"}).encode()),
        _FakeMessage(json.dumps({"event": "b"}).encode()),
    ]

    class _ConsumeTrainFakeQueue(_TrainFakeQueue):
        def iterator(self):
            return _FakeQueueIterator(messages)

    class _ConsumeTrainFakeChannel(_TrainFakeChannel):
        async def declare_queue(self, name, durable=True, arguments=None):
            queue = _ConsumeTrainFakeQueue(name, arguments)
            self.queues[name] = queue
            return queue

    fake_connection = _TrainFakeConnection()
    fake_connection.channel_obj = _ConsumeTrainFakeChannel()

    async def fake_get_connection():
        return fake_connection

    monkeypatch.setattr(rabbitmq_client, "get_rabbitmq_connection", fake_get_connection)

    seen = []

    async def handler(payload):
        seen.append(payload)

    await rabbitmq_client.consume_training_trigger_events(handler)

    assert seen == [{"event": "a"}, {"event": "b"}]
    assert fake_connection.channel_obj.qos == 1
