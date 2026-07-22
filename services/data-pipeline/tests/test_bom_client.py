"""Tests for ecolens.ingestion.sources.bom.client.BomClient."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from ecolens.ingestion.sources.bom.client import BomClient


class TestParseStationJson:
    def test_parses_observations_within_window(self):
        client = BomClient()
        raw = '{"observations": {"data": [{"local_date_time_full": "20260720140000", "air_temp": 25.0}]}}'
        since = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)
        until = datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc)
        rows = client.parse_station_json(raw, "NSW1", "066037", since, until)
        assert len(rows) == 1
        assert rows[0]["temp_c"] == 25.0

    def test_observations_outside_window_are_dropped(self):
        client = BomClient()
        raw = '{"observations": {"data": [{"local_date_time_full": "20260720140000", "air_temp": 25.0}]}}'
        since = datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc)
        until = datetime(2026, 7, 21, 1, 0, tzinfo=timezone.utc)
        rows = client.parse_station_json(raw, "NSW1", "066037", since, until)
        assert rows == []

    def test_malformed_json_returns_empty_list(self):
        client = BomClient()
        rows = client.parse_station_json(
            "not json",
            "NSW1",
            "066037",
            datetime.min.replace(tzinfo=timezone.utc),
            datetime.max.replace(tzinfo=timezone.utc),
        )
        assert rows == []

    def test_empty_observations_returns_empty_list(self):
        client = BomClient()
        raw = '{"observations": {"data": []}}'
        rows = client.parse_station_json(
            raw,
            "NSW1",
            "066037",
            datetime.min.replace(tzinfo=timezone.utc),
            datetime.max.replace(tzinfo=timezone.utc),
        )
        assert rows == []


class TestFetchStation:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_fetch(self):
        respx.get("http://www.bom.gov.au/fwo/066037/observations.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "observations": {
                        "data": [
                            {"local_date_time_full": "20260720140000", "air_temp": 25.0}
                        ]
                    }
                },
            )
        )
        client = BomClient()
        async with httpx.AsyncClient() as http:
            rows = await client.fetch_station(
                http,
                "NSW1",
                "066037",
                datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc),
            )
        assert len(rows) == 1
        assert rows[0]["region"] == "NSW1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_then_succeeds(self, monkeypatch):
        route = respx.get("http://www.bom.gov.au/fwo/066037/observations.json")
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(
                200,
                json={
                    "observations": {
                        "data": [
                            {"local_date_time_full": "20260720140000", "air_temp": 25.0}
                        ]
                    }
                },
            ),
        ]

        async def no_sleep(_seconds):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        client = BomClient()
        async with httpx.AsyncClient() as http:
            rows = await client.fetch_station(
                http,
                "NSW1",
                "066037",
                datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc),
            )
        assert len(rows) == 1
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_retries_fail_raises(self, monkeypatch):
        respx.get("http://www.bom.gov.au/fwo/066037/observations.json").mock(
            return_value=httpx.Response(500)
        )

        async def no_sleep(_seconds):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        client = BomClient()
        with pytest.raises(httpx.HTTPStatusError):
            async with httpx.AsyncClient() as http:
                await client.fetch_station(
                    http,
                    "NSW1",
                    "066037",
                    datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc),
                    datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc),
                )
