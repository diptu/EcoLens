"""End-to-end (mocked HTTP) tests for ecolens.ingestion.sources.bom.engine.BomFetcher."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from ecolens.ingestion.sources.bom.engine import BomFetcher

STATIONS = {"NSW1": "066037", "VIC1": "086282"}


@pytest.fixture
def no_sleep(monkeypatch):
    """Skip the client's real retry backoff sleeps in tests that hit 500s."""

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)


def _obs_response(temp_c: float, region: str) -> httpx.Response:
    from ecolens.ingestion.sources.bom.schema import AUSTRALIA_UTC_OFFSETS

    # normalize_observation() treats local_date_time_full as local time
    # and subtracts the region's UTC offset to get back to UTC — so to
    # land the resulting `ts` at "now" (inside the fetcher's default
    # 1-hour window), the fixture timestamp must be "now" *plus* the
    # offset, expressed as if it were local time.
    offset = AUSTRALIA_UTC_OFFSETS[region]
    local_now = datetime.now(timezone.utc) + timedelta(hours=offset)
    return httpx.Response(
        200,
        json={
            "observations": {
                "data": [
                    {
                        "local_date_time_full": local_now.strftime("%Y%m%d%H%M%S"),
                        "air_temp": temp_c,
                    }
                ]
            }
        },
    )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_uses_live_api_when_available(tmp_path):
    respx.get("http://www.bom.gov.au/fwo/066037/observations.json").mock(
        return_value=_obs_response(25.0, "NSW1")
    )
    respx.get("http://www.bom.gov.au/fwo/086282/observations.json").mock(
        return_value=_obs_response(18.0, "VIC1")
    )

    fetcher = BomFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
    async with httpx.AsyncClient() as client:
        docs = await fetcher.fetch(client)

    assert {d["region"] for d in docs} == {"NSW1", "VIC1"}
    run_ids = {d["ingest_run_id"] for d in docs}
    assert len(run_ids) == 1  # every doc in a fetch shares one run id


@pytest.mark.asyncio
@respx.mock
async def test_one_station_failing_does_not_abort_the_others(tmp_path, no_sleep):
    respx.get("http://www.bom.gov.au/fwo/066037/observations.json").mock(
        return_value=_obs_response(25.0, "NSW1")
    )
    respx.get("http://www.bom.gov.au/fwo/086282/observations.json").mock(
        return_value=httpx.Response(500)
    )

    fetcher = BomFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
    async with httpx.AsyncClient() as client:
        docs = await fetcher.fetch(client)

    assert {d["region"] for d in docs} == {"NSW1"}


@pytest.mark.asyncio
@respx.mock
async def test_falls_back_to_cache_when_live_api_down(tmp_path, no_sleep):
    from ecolens.ingestion.sources.bom.cache import write_cache

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    write_cache(
        tmp_path,
        [
            {
                "ts": since,
                "region": "NSW1",
                "station_id": "066037",
                "station_name": "Sydney",
                "schema_version": "1.0",
                "temp_c": 21.0,
                "source": "bom",
            }
        ],
    )
    respx.get("http://www.bom.gov.au/fwo/066037/observations.json").mock(
        return_value=httpx.Response(500)
    )
    respx.get("http://www.bom.gov.au/fwo/086282/observations.json").mock(
        return_value=httpx.Response(500)
    )

    fetcher = BomFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
    async with httpx.AsyncClient() as client:
        docs = await fetcher.fetch(
            client,
            since=since - timedelta(minutes=5),
            until=since + timedelta(minutes=5),
        )

    assert len(docs) == 1
    assert docs[0]["region"] == "NSW1"


@pytest.mark.asyncio
@respx.mock
async def test_falls_back_to_synthetic_stub_when_nothing_else_available(
    tmp_path, no_sleep
):
    respx.get("http://www.bom.gov.au/fwo/066037/observations.json").mock(
        return_value=httpx.Response(500)
    )
    respx.get("http://www.bom.gov.au/fwo/086282/observations.json").mock(
        return_value=httpx.Response(500)
    )

    fetcher = BomFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
    async with httpx.AsyncClient() as client:
        docs = await fetcher.fetch(client)

    assert {d["region"] for d in docs} == {"NSW1", "VIC1"}
    assert all(d["data_quality_status"] == "preliminary" for d in docs)


def test_until_before_since_raises(tmp_path):
    fetcher = BomFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(
            fetcher.fetch(
                httpx.AsyncClient(), since=now, until=now - timedelta(hours=1)
            )
        )


class TestConstruction:
    def test_cache_dir_created_on_init(self, tmp_path):
        new_dir = tmp_path / "deeply" / "nested" / "cache"
        BomFetcher(bom_stations=STATIONS, cache_dir=new_dir)
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_custom_stations_override_default(self, tmp_path):
        custom = {"NSW1": "999999"}
        fetcher = BomFetcher(bom_stations=custom, cache_dir=tmp_path)
        assert fetcher.stations == custom

    def test_default_construction_uses_settings_stations(self, tmp_path):
        fetcher = BomFetcher(cache_dir=tmp_path)
        assert len(fetcher.stations) == 6
