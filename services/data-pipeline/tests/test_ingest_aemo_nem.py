import pytest

from app.service.pipeline.tasks import ingest_aemo_nem

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _PassthroughBreaker:
    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def _bypass_real_breaker(monkeypatch):
    monkeypatch.setattr(
        ingest_aemo_nem, "get_breaker", lambda name: _PassthroughBreaker()
    )


async def test_run_falls_back_to_synthetic_stub_without_live_api_or_cache():
    # No live AEMO endpoint reachable as designed (the real fetch always
    # returns None -- see _try_live_api's docstring), and no
    # /data/raw/aemo/nem cache dir on this machine -> synthetic stub path.
    df = await ingest_aemo_nem.run(lookback_minutes=15)

    assert not df.empty
    assert set(df["region"]) == set(ingest_aemo_nem.REGIONS)


async def test_synthetic_stub_columns_match_the_raw_aemo_nem_dispatch_schema():
    df = ingest_aemo_nem._synthetic_stub(15)

    expected = {
        "ts",
        "region",
        "demand_mw",
        "price_mwh",
        "coal_mw",
        "gas_mw",
        "hydro_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_mw",
        "net_import_mw",
        "source",
        "ingested_at",
        "ingest_run_id",
    }
    assert set(df.columns) == expected
