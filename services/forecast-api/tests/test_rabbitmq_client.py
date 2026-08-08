"""Ported from data-pipeline's `tests/test_rabbitmq_client.py`, the
training-trigger topology section only -- this service's `app.db.
rabbitmq` has no landing-queue side at all (that stays split between
`services/ingestion` (publish) and `services/waerehouse` (consume));
this module is publish+consume for the training-trigger queue only."""

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


async def test_close_rabbitmq_closes_and_clears_the_cached_connection():
    fake_connection = _TrainFakeConnection()
    rabbitmq_client._connection = fake_connection

    await rabbitmq_client.close_rabbitmq()

    assert fake_connection.is_closed is True
    assert rabbitmq_client._connection is None


async def test_close_rabbitmq_is_a_noop_when_nothing_is_connected():
    await rabbitmq_client.close_rabbitmq()  # should not raise


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


async def test_a_failing_handler_propagates_after_processing_earlier_messages(
    monkeypatch,
):
    """Unlike `consume_landed_events` (which wraps each message in its
    own try/except, application-level DLQ), `consume_training_trigger_
    events` has no per-message try/except at all: `message.process(
    requeue=False)`'s `__aexit__` nacks then re-raises, which escapes the
    `async for` and ends the consume loop -- the queue's native
    `x-dead-letter-exchange` argument (`_declare_training_trigger_
    topology`) is what actually dead-letters the failed message at the
    broker level, so no application-level catch is needed here. This
    pins that real behavior: earlier messages in the same batch were
    already handed to the handler before the exception propagates."""

    class _FakeMessage:
        def __init__(self, body):
            self.body = body

        def process(self, requeue=False):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False  # never suppresses -- matches real aio_pika behavior

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
        _FakeMessage(json.dumps({"architecture": "lstm"}).encode()),
        _FakeMessage(json.dumps({"architecture": "bad"}).encode()),
        _FakeMessage(json.dumps({"architecture": "tft"}).encode()),
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
        seen.append(payload["architecture"])
        if payload["architecture"] == "bad":
            raise RuntimeError("no warm-startable version -- simulated failure")

    with pytest.raises(RuntimeError):
        await rabbitmq_client.consume_training_trigger_events(handler)

    # The first (good) message was handled before the failing one raised
    # -- confirms the loop processes messages one at a time, in order,
    # rather than batching in a way that would hide this.
    assert seen == ["lstm", "bad"]
