"""Tests for ecolens.ingestion.sources.bom.historical_transformers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ecolens.ingestion.sources.bom.historical_transformers import (
    build_open_meteo_url,
    parse_open_meteo_response,
)
from ecolens.ingestion.sources.bom.schema import (
    DEFAULT_BOM_STATIONS,
    PARAM_MAP,
    STATION_COORDS,
)


class TestBuildUrl:
    def test_contains_required_params(self):
        url = build_open_meteo_url(
            "NSW1",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 7, tzinfo=timezone.utc),
        )
        assert "archive-api.open-meteo.com" in url
        assert "latitude=-33.8576" in url
        assert "longitude=151.2157" in url
        assert "start_date=2024-01-01" in url
        assert "end_date=2024-01-07" in url
        assert "timezone=UTC" in url
        assert "wind_speed_unit=kmh" in url
        for param in PARAM_MAP:
            assert param in url

    @pytest.mark.parametrize("region", list(STATION_COORDS))
    def test_per_station_coords(self, region):
        lat, lon = STATION_COORDS[region]
        url = build_open_meteo_url(
            region,
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        assert f"latitude={lat}" in url
        assert f"longitude={lon}" in url

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError):
            build_open_meteo_url(
                "INVALID",
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 2, tzinfo=timezone.utc),
            )


def _full_payload(hours: int = 24) -> dict:
    return {
        "latitude": -33.8576,
        "longitude": 151.2157,
        "timezone": "UTC",
        "hourly": {
            "time": [f"2024-01-01T{h:02d}:00" for h in range(hours)],
            "temperature_2m": [22.0 + h * 0.1 for h in range(hours)],
            "apparent_temperature": [21.0 + h * 0.1 for h in range(hours)],
            "relative_humidity_2m": [60.0] * hours,
            "dew_point_2m": [15.0] * hours,
            "wind_speed_10m": [12.0] * hours,
            "wind_direction_10m": [180.0] * hours,
            "wind_gusts_10m": [25.0] * hours,
            "surface_pressure": [1013.0] * hours,
            "precipitation": [0.0] * hours,
            "cloud_cover": [50.0] * hours,
        },
    }


class TestParseResponse:
    def test_each_hour_becomes_two_30min_rows(self):
        rows = parse_open_meteo_response(
            _full_payload(24), "NSW1", DEFAULT_BOM_STATIONS
        )
        assert len(rows) == 48  # 24 hours -> 48 half-hour slots

    def test_row_fields(self):
        rows = parse_open_meteo_response(
            _full_payload(24), "NSW1", DEFAULT_BOM_STATIONS
        )
        for r in rows:
            assert r["region"] == "NSW1"
            assert r["station_id"] == "066037"
            assert r["station_name"] == "Sydney - Observatory Hill"
            assert r["schema_version"] == "1.0"
            assert r["source"] == "open_meteo_era5"
            assert r["data_quality_status"] == "final"

    def test_hour_duplicated_at_00_and_30(self):
        rows = parse_open_meteo_response(_full_payload(1), "NSW1", DEFAULT_BOM_STATIONS)
        assert len(rows) == 2
        assert rows[0]["ts"].minute == 0
        assert rows[1]["ts"].minute == 30
        assert rows[0]["ts"].hour == rows[1]["ts"].hour
        # Same weather values in both half-hour slots (ERA5 has no finer grain)
        assert rows[0]["temp_c"] == rows[1]["temp_c"]

    def test_first_row_values(self):
        payload = _full_payload(2)
        rows = parse_open_meteo_response(payload, "NSW1", DEFAULT_BOM_STATIONS)
        first = rows[0]
        assert first["temp_c"] == 22.0
        assert first["humidity_pct"] == 60.0
        assert first["wind_speed_kmh"] == 12.0
        assert first["wind_direction_deg"] == 180.0
        assert first["pressure_hpa"] == 1013.0
        assert first["cloud_cover_pct"] == 50.0
        assert first["cloud_oktas"] == 4.0  # 50 / 12.5

    def test_malformed_payload_returns_none(self):
        assert parse_open_meteo_response({}, "NSW1", DEFAULT_BOM_STATIONS) is None

    def test_empty_time_array_returns_empty_list(self):
        assert (
            parse_open_meteo_response(
                {"hourly": {"time": []}}, "NSW1", DEFAULT_BOM_STATIONS
            )
            == []
        )

    def test_missing_arrays_default_to_none(self):
        payload = {
            "hourly": {
                "time": ["2024-01-01T00:00"],
                "temperature_2m": [22.5],
                # every other parameter missing
            }
        }
        rows = parse_open_meteo_response(payload, "NSW1", DEFAULT_BOM_STATIONS)
        assert len(rows) == 2
        assert rows[0]["temp_c"] == 22.5
        assert rows[0]["humidity_pct"] is None
        assert rows[0]["wind_speed_kmh"] is None
