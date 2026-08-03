import pytest

from app.service.pipeline.tasks import ingest_bom

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _PassthroughBreaker:
    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def _bypass_real_breaker(monkeypatch):
    monkeypatch.setattr(ingest_bom, "get_breaker", lambda name: _PassthroughBreaker())


async def test_run_falls_back_to_synthetic_stub_without_live_bom_or_cache(monkeypatch):
    # No live network mocked, no /data/raw/bom cache directory on this
    # machine -> exercises the real fallback-to-synthetic-stub path.
    df = await ingest_bom.run(lookback_minutes=60)

    assert not df.empty
    assert set(df["region"]) == set(ingest_bom.get_settings().bom_stations)


async def test_synthetic_stub_columns_match_the_raw_bom_observations_schema():
    df = ingest_bom._synthetic_stub(60)

    expected = {
        "ts",
        "station_id",
        "region",
        "temp_c",
        "apparent_temp_c",
        "dew_point_c",
        "humidity_pct",
        "wind_speed_kmh",
        "wind_direction_deg",
        "wind_gust_kmh",
        "pressure_hpa",
        "rain_since_9am_mm",
        "cloud_oktas",
        "source",
        "ingested_at",
        "ingest_run_id",
    }
    assert set(df.columns) == expected
