"""Tests for ecolens.ingestion.sources.bom.client.BomClient."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from ecolens.ingestion.sources.bom.client import BomClient


def _v1_payload(
    *, observation_time: str = "2026-07-20T14:00:00Z", temp: float = 25.0
) -> str:
    return json.dumps(
        {
            "metadata": {
                "response_timestamp": "2026-07-20T14:01:00Z",
                "issue_time": "2026-07-20T13:56:00Z",
                "observation_time": observation_time,
                "copyright": "This application programming interface (API) is owned by the Bureau of Meteorology.",
            },
            "data": {
                "temp": temp,
                "temp_feels_like": temp - 2.0,
                "wind": {"speed_kilometre": 19, "speed_knot": 10, "direction": "WNW"},
                "gust": None,
                "rain_since_9am": 0,
                "humidity": 89,
                "station": {
                    "bom_id": "066214",
                    "name": "Sydney - Observatory Hill",
                    "distance": 560,
                },
            },
        }
    )


class TestParseObservationJson:
    def test_parses_observation_within_window(self):
        client = BomClient()
        since = datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc)
        until = datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc)
        rows = client.parse_observation_json(
            _v1_payload(), "NSW1", "r3gx2s", since, until
        )
        assert len(rows) == 1
        assert rows[0]["temp_c"] == 25.0
        assert rows[0]["station_id"] == "066214"

    def test_observation_outside_window_is_dropped(self):
        client = BomClient()
        since = datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc)
        until = datetime(2026, 7, 21, 1, 0, tzinfo=timezone.utc)
        rows = client.parse_observation_json(
            _v1_payload(), "NSW1", "r3gx2s", since, until
        )
        assert rows == []

    def test_malformed_json_returns_empty_list(self):
        client = BomClient()
        rows = client.parse_observation_json(
            "not json",
            "NSW1",
            "r3gx2s",
            datetime.min.replace(tzinfo=timezone.utc),
            datetime.max.replace(tzinfo=timezone.utc),
        )
        assert rows == []

    def test_empty_data_returns_empty_list(self):
        client = BomClient()
        raw = json.dumps({"metadata": {}, "data": {}})
        rows = client.parse_observation_json(
            raw,
            "NSW1",
            "r3gx2s",
            datetime.min.replace(tzinfo=timezone.utc),
            datetime.max.replace(tzinfo=timezone.utc),
        )
        assert rows == []


class TestFetchStation:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_fetch(self):
        respx.get(
            "https://api.weather.bom.gov.au/v1/locations/r3gx2s/observations"
        ).mock(return_value=httpx.Response(200, content=_v1_payload()))
        client = BomClient()
        async with httpx.AsyncClient() as http:
            rows = await client.fetch_station(
                http,
                "NSW1",
                "r3gx2s",
                datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc),
            )
        assert len(rows) == 1
        assert rows[0]["region"] == "NSW1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_then_succeeds(self, monkeypatch):
        route = respx.get(
            "https://api.weather.bom.gov.au/v1/locations/r3gx2s/observations"
        )
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(200, content=_v1_payload()),
        ]

        async def no_sleep(_seconds):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        client = BomClient()
        async with httpx.AsyncClient() as http:
            rows = await client.fetch_station(
                http,
                "NSW1",
                "r3gx2s",
                datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc),
            )
        assert len(rows) == 1
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_retries_fail_raises(self, monkeypatch):
        respx.get(
            "https://api.weather.bom.gov.au/v1/locations/r3gx2s/observations"
        ).mock(return_value=httpx.Response(500))

        async def no_sleep(_seconds):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        client = BomClient()
        with pytest.raises(httpx.HTTPStatusError):
            async with httpx.AsyncClient() as http:
                await client.fetch_station(
                    http,
                    "NSW1",
                    "r3gx2s",
                    datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc),
                    datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc),
                )
