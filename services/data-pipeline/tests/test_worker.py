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
