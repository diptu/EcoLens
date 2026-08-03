import pytest

from app.service.pipeline.tasks import ingest_aemo_wem

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
        ingest_aemo_wem, "get_breaker", lambda name: _PassthroughBreaker()
    )


async def test_run_falls_back_to_synthetic_stub_without_live_api_or_cache():
    df = await ingest_aemo_wem.run(lookback_minutes=60)

    assert not df.empty
    assert set(df["region"]) == {"WEM"}


async def test_synthetic_stub_columns_match_the_raw_aemo_wem_dispatch_schema():
    df = ingest_aemo_wem._synthetic_stub(60)

    expected = {
        "ts",
        "region",
        "demand_mw",
        "price_mwh",
        "coal_mw",
        "gas_mw",
        "diesel_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_mw",
        "biomass_mw",
        "total_generation_mw",
        "source",
        "ingested_at",
        "ingest_run_id",
    }
    assert set(df.columns) == expected
