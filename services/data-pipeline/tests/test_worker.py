import pytest

from app.service import worker

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_run_consumes_events_and_closes_the_connection_on_exit(monkeypatch):
    calls = []

    async def fake_consume(handler):
        calls.append(("consume", handler))

    async def fake_close():
        calls.append(("close", None))

    monkeypatch.setattr(worker, "consume_landed_events", fake_consume)
    monkeypatch.setattr(worker, "close_rabbitmq", fake_close)

    await worker.run()

    assert calls[0][0] == "consume"
    assert calls[0][1] is worker.sync_landed_event
    assert calls[1] == ("close", None)


async def test_run_closes_the_connection_even_if_consuming_raises(monkeypatch):
    async def fake_consume(handler):
        raise RuntimeError("broker connection dropped")

    closed = []

    async def fake_close():
        closed.append(True)

    monkeypatch.setattr(worker, "consume_landed_events", fake_consume)
    monkeypatch.setattr(worker, "close_rabbitmq", fake_close)

    with pytest.raises(RuntimeError, match="broker connection dropped"):
        await worker.run()

    assert closed == [True]


async def test_run_is_a_noop_when_warehouse_sync_consumer_disabled(monkeypatch):
    """`services/waerehouse/TODO.md` Phase 4's cutover switch — flipping
    `warehouse_sync_consumer_enabled` off must not open a RabbitMQ
    connection at all, not just skip consuming from it."""
    calls = []

    async def fake_consume(handler):
        calls.append("consume")

    async def fake_close():
        calls.append("close")

    class FakeSettings:
        warehouse_sync_consumer_enabled = False

    monkeypatch.setattr(worker, "consume_landed_events", fake_consume)
    monkeypatch.setattr(worker, "close_rabbitmq", fake_close)
    monkeypatch.setattr(worker, "get_settings", lambda: FakeSettings())

    await worker.run()

    assert calls == []
