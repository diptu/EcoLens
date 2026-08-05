from datetime import datetime, timezone

import pandas as pd
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


# ────────────────────────────────────────────────────────────────────
# Real historical fetch — Open-Meteo's ERA5 archive
# ────────────────────────────────────────────────────────────────────


def _open_meteo_response(n_hours: int = 2) -> dict:
    """Matches the real `archive-api.open-meteo.com/v1/archive` shape --
    verified live (2026-08-05) before writing this module."""
    return {
        "hourly": {
            "time": [f"2026-07-01T{h:02d}:00" for h in range(n_hours)],
            "temperature_2m": [14.8, 14.2][:n_hours],
            "apparent_temperature": [13.5, 13.1][:n_hours],
            "relative_humidity_2m": [84, 85][:n_hours],
            "dew_point_2m": [12.2, 12.0][:n_hours],
            "wind_speed_10m": [13.1, 12.4][:n_hours],
            "wind_direction_10m": [353, 350][:n_hours],
            "wind_gusts_10m": [25.6, 24.0][:n_hours],
            "surface_pressure": [1018.4, 1018.1][:n_hours],
            "cloud_cover": [4, 25][:n_hours],
        }
    }


class _FakeResponse:
    def __init__(self, *, json_body: dict, status_code: int = 200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_body


class _FakeClient:
    """Duck-typed stand-in for `httpx.AsyncClient` -- `_fetch_open_meteo_station`
    always hits the same base URL, differing only by `params`, so this
    returns queued responses in call order (matching `Settings.
    bom_stations`' fixed dict iteration order) rather than keying by URL."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def test_fetch_historical_range_joins_all_six_real_stations(monkeypatch):
    import httpx

    fake = _FakeClient(
        [_FakeResponse(json_body=_open_meteo_response()) for _ in range(6)]
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _AsyncCtx(fake))

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    df = await ingest_bom._fetch_historical_range(start, end)

    assert len(df) == 12  # 6 stations x 2 hours
    assert set(df["region"]) == set(ingest_bom.get_settings().bom_stations)
    assert set(df["station_id"]) == set(ingest_bom.get_settings().bom_stations.values())


async def test_fetch_open_meteo_station_maps_real_response_fields():
    fake = _FakeClient([_FakeResponse(json_body=_open_meteo_response())])

    df = await ingest_bom._fetch_open_meteo_station(
        fake,
        "066037",
        "NSW1",
        (-33.9465, 151.1731),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert len(df) == 2
    row = df.iloc[0]
    assert row["station_id"] == "066037"
    assert row["region"] == "NSW1"
    assert row["temp_c"] == 14.8
    assert row["apparent_temp_c"] == 13.5
    assert row["dew_point_c"] == 12.2
    assert row["humidity_pct"] == 84
    assert row["wind_speed_kmh"] == 13.1
    assert row["wind_direction_deg"] == 353
    assert row["wind_gust_kmh"] == 25.6
    assert row["pressure_hpa"] == 1018.4
    # cloud_cover=4% -> 4/12.5 = 0.32 oktas, rounded to 1dp (real, documented conversion)
    assert row["cloud_oktas"] == pytest.approx(0.3)
    # No Open-Meteo equivalent -- left honestly NULL, not a fabricated 0.
    assert pd.isna(row["rain_since_9am_mm"])


async def test_fetch_historical_range_skips_a_failing_station_and_keeps_going(
    monkeypatch,
):
    import httpx

    # NSW1 (first in Settings.bom_stations) fails; the other 5 succeed.
    responses = [RuntimeError("connection reset")] + [
        _FakeResponse(json_body=_open_meteo_response()) for _ in range(5)
    ]
    fake = _FakeClient(responses)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _AsyncCtx(fake))

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    df = await ingest_bom._fetch_historical_range(start, end)

    assert "NSW1" not in set(df["region"])
    assert len(df) == 10  # 5 surviving stations x 2 hours


async def test_fetch_historical_range_skips_a_station_with_no_coords(monkeypatch):
    import httpx

    monkeypatch.setattr(ingest_bom, "_STATION_COORDS", {})  # no station has coords
    fake = _FakeClient([])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _AsyncCtx(fake))

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    df = await ingest_bom._fetch_historical_range(start, end)

    assert df.empty
    assert fake.calls == []  # never even attempted a request


async def test_historical_range_columns_match_the_raw_bom_observations_schema(
    monkeypatch,
):
    import httpx

    fake = _FakeClient(
        [_FakeResponse(json_body=_open_meteo_response()) for _ in range(6)]
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _AsyncCtx(fake))

    df = await ingest_bom._fetch_historical_range(
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

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


async def test_run_with_start_and_end_routes_to_the_historical_fetch(monkeypatch):
    called_with = {}

    async def fake_historical_range(start, end):
        called_with["start"] = start
        called_with["end"] = end
        return pd.DataFrame([{"ts": start, "region": "NSW1", "temp_c": 20.0}])

    monkeypatch.setattr(ingest_bom, "_fetch_historical_range", fake_historical_range)

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 2, tzinfo=timezone.utc)
    df = await ingest_bom.run(start=start, end=end)

    assert called_with == {"start": start, "end": end}
    assert len(df) == 1


class _AsyncCtx:
    """`async with httpx.AsyncClient(...) as client:` support for `_FakeClient`."""

    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc):
        return False
