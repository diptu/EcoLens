"""End-to-end (mocked HTTP) tests for ecolens.ingestion.sources.bom.engine.BomFetcher."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from ecolens.ingestion.sources.bom.engine import BomFetcher

GEOHASHES = {"NSW1": "r3gx2s", "VIC1": "r1qcxv"}


@pytest.fixture
def no_sleep(monkeypatch):
    """Skip the client's real retry backoff sleeps in tests that hit 500s."""

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)


def _obs_response(temp_c: float, bom_id: str, name: str) -> httpx.Response:
    # v1's observation_time is UTC already (no local-time offset math
    # needed, unlike the legacy endpoint) -- "now" lands inside the
    # fetcher's default 1-hour window directly.
    now = datetime.now(timezone.utc)
    return httpx.Response(
        200,
        content=json.dumps(
            {
                "metadata": {"observation_time": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                "data": {
                    "temp": temp_c,
                    "temp_feels_like": temp_c,
                    "wind": {"speed_kilometre": 10, "direction": "N"},
                    "gust": None,
                    "rain_since_9am": 0,
                    "humidity": 50,
                    "station": {"bom_id": bom_id, "name": name, "distance": 100},
                },
            }
        ),
    )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_uses_live_api_when_available(tmp_path):
    respx.get("https://api.weather.bom.gov.au/v1/locations/r3gx2s/observations").mock(
        return_value=_obs_response(25.0, "066214", "Sydney")
    )
    respx.get("https://api.weather.bom.gov.au/v1/locations/r1qcxv/observations").mock(
        return_value=_obs_response(18.0, "086338", "Melbourne")
    )

    fetcher = BomFetcher(bom_geohashes=GEOHASHES, cache_dir=tmp_path)
    async with httpx.AsyncClient() as client:
        docs = await fetcher.fetch(client)

    assert {d["region"] for d in docs} == {"NSW1", "VIC1"}
    run_ids = {d["ingest_run_id"] for d in docs}
    assert len(run_ids) == 1  # every doc in a fetch shares one run id


@pytest.mark.asyncio
@respx.mock
async def test_one_station_failing_does_not_abort_the_others(tmp_path, no_sleep):
    respx.get("https://api.weather.bom.gov.au/v1/locations/r3gx2s/observations").mock(
        return_value=_obs_response(25.0, "066214", "Sydney")
    )
    respx.get("https://api.weather.bom.gov.au/v1/locations/r1qcxv/observations").mock(
        return_value=httpx.Response(500)
    )

    fetcher = BomFetcher(bom_geohashes=GEOHASHES, cache_dir=tmp_path)
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
    respx.get("https://api.weather.bom.gov.au/v1/locations/r3gx2s/observations").mock(
        return_value=httpx.Response(500)
    )
    respx.get("https://api.weather.bom.gov.au/v1/locations/r1qcxv/observations").mock(
        return_value=httpx.Response(500)
    )

    fetcher = BomFetcher(bom_geohashes=GEOHASHES, cache_dir=tmp_path)
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
    respx.get("https://api.weather.bom.gov.au/v1/locations/r3gx2s/observations").mock(
        return_value=httpx.Response(500)
    )
    respx.get("https://api.weather.bom.gov.au/v1/locations/r1qcxv/observations").mock(
        return_value=httpx.Response(500)
    )

    fetcher = BomFetcher(bom_geohashes=GEOHASHES, cache_dir=tmp_path)
    async with httpx.AsyncClient() as client:
        docs = await fetcher.fetch(client)

    # Synthetic stub always covers all 6 canonical regions, regardless
    # of which (2, here) geohashes the live tier was configured with.
    assert {d["region"] for d in docs} == {
        "NSW1",
        "QLD1",
        "VIC1",
        "SA1",
        "TAS1",
        "WEM",
    }
    assert all(d["data_quality_status"] == "preliminary" for d in docs)


def test_until_before_since_raises(tmp_path):
    fetcher = BomFetcher(bom_geohashes=GEOHASHES, cache_dir=tmp_path)
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
        BomFetcher(bom_geohashes=GEOHASHES, cache_dir=new_dir)
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_custom_geohashes_override_default(self, tmp_path):
        custom = {"NSW1": "abcdef"}
        fetcher = BomFetcher(bom_geohashes=custom, cache_dir=tmp_path)
        assert fetcher.geohashes == custom

    def test_default_construction_uses_settings_geohashes(self, tmp_path):
        fetcher = BomFetcher(cache_dir=tmp_path)
        assert len(fetcher.geohashes) == 6
