import pytest

from app.service.pipeline.tasks import ingest_holidays

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _PassthroughBreaker:
    """No Redis needed — just calls fn() directly, like a closed breaker."""

    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def _bypass_real_breaker(monkeypatch):
    monkeypatch.setattr(
        ingest_holidays, "get_breaker", lambda name: _PassthroughBreaker()
    )


async def test_run_with_default_year_does_not_raise_unbound_local_error():
    # Regression test: `year` used to be reassigned inside the nested
    # _do_fetch() closure, making it a local variable for the whole
    # closure and raising UnboundLocalError on `if year is None`.
    df = await ingest_holidays.run()

    assert not df.empty
    assert set(df["region"]) == set(ingest_holidays.REGIONS)


async def test_run_with_explicit_year_uses_it():
    df = await ingest_holidays.run(year=2030)

    dates = df["date"].astype(str)
    assert any(d.startswith("2030-") for d in dates)


async def test_run_default_year_uses_current_year(monkeypatch):
    import datetime

    class FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2027, 6, 1)

    monkeypatch.setattr(ingest_holidays, "date", FixedDate)

    df = await ingest_holidays.run()

    dates = df["date"].astype(str)
    assert all(d.startswith("2027-") for d in dates)
