"""Tests for ecolens.ingestion.sources.bom.historical_client.OpenMeteoClient."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from ecolens.ingestion.sources.bom.historical_client import OpenMeteoClient
from ecolens.ingestion.sources.bom.schema import DEFAULT_BOM_STATIONS

URL_REGEX = r"https://archive-api\.open-meteo\.com/v1/archive.*"


def _payload(hours: int = 2) -> dict:
    return {
        "hourly": {
            "time": [f"2024-01-0{1 + h // 24}T{h % 24:02d}:00" for h in range(hours)],
            "temperature_2m": [20.0] * hours,
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_fetch_chunk_success():
    respx.get(url__regex=URL_REGEX).mock(
        return_value=httpx.Response(200, json=_payload(2))
    )
    client = OpenMeteoClient()
    async with httpx.AsyncClient() as http:
        rows = await client.fetch_chunk(
            http,
            "NSW1",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            DEFAULT_BOM_STATIONS,
        )
    assert rows is not None
    assert len(rows) == 4  # 2 hours -> 4 half-hour rows


@pytest.mark.asyncio
@respx.mock
async def test_fetch_chunk_retries_then_succeeds(monkeypatch):
    route = respx.get(url__regex=URL_REGEX)
    route.side_effect = [httpx.Response(500), httpx.Response(200, json=_payload(1))]

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)
    client = OpenMeteoClient()
    async with httpx.AsyncClient() as http:
        rows = await client.fetch_chunk(
            http,
            "NSW1",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            DEFAULT_BOM_STATIONS,
        )
    assert rows is not None
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_chunk_returns_none_after_all_retries_fail(monkeypatch):
    respx.get(url__regex=URL_REGEX).mock(return_value=httpx.Response(500))

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)
    client = OpenMeteoClient()
    async with httpx.AsyncClient() as http:
        rows = await client.fetch_chunk(
            http,
            "NSW1",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            DEFAULT_BOM_STATIONS,
        )
    assert rows is None
