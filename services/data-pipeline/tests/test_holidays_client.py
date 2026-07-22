"""Tests for ecolens.ingestion.sources.holidays.client.HolidayClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from conftest import FakeRedis

from ecolens.ingestion.circuit_breaker import CircuitBreaker
from ecolens.ingestion.sources.holidays.client import HolidayClient
from ecolens.ingestion.storage.settings import MongoSettings

DATASTORE_URL_REGEX = r"https://data\.gov\.au/data/api/3/action/datastore_search.*"


async def _no_sleep(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_year_parses_matching_records():
    respx.get(url__regex=DATASTORE_URL_REGEX).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "records": [
                        {
                            "Date": "2026-01-01",
                            "Name": "New Year's Day",
                            "Jurisdiction": "nsw",
                        },
                        {
                            "Date": "2025-01-01",
                            "Name": "New Year's Day",
                            "Jurisdiction": "nsw",
                        },
                    ]
                }
            },
        )
    )
    client = HolidayClient()
    async with httpx.AsyncClient() as http:
        docs = await client.fetch_year(http, 2026)

    assert docs is not None
    assert len(docs) == 1
    assert docs[0]["region"] == "NSW1"
    assert docs[0]["date"] == "2026-01-01"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_year_returns_none_on_empty_records():
    respx.get(url__regex=DATASTORE_URL_REGEX).mock(
        return_value=httpx.Response(200, json={"result": {"records": []}})
    )
    client = HolidayClient()
    async with httpx.AsyncClient() as http:
        docs = await client.fetch_year(http, 2026)
    assert docs is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_year_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    respx.get(url__regex=DATASTORE_URL_REGEX).mock(return_value=httpx.Response(500))
    client = HolidayClient()
    async with httpx.AsyncClient() as http:
        docs = await client.fetch_year(http, 2026)
    assert docs is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_year_ignores_unknown_jurisdiction():
    respx.get(url__regex=DATASTORE_URL_REGEX).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "records": [
                        {
                            "Date": "2026-01-01",
                            "Name": "Bogus Day",
                            "Jurisdiction": "not_a_state",
                        }
                    ]
                }
            },
        )
    )
    client = HolidayClient()
    async with httpx.AsyncClient() as http:
        docs = await client.fetch_year(http, 2026)
    assert docs == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_year_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    route = respx.get(url__regex=DATASTORE_URL_REGEX)
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(
            200,
            json={
                "result": {
                    "records": [
                        {
                            "Date": "2026-01-01",
                            "Name": "New Year's Day",
                            "Jurisdiction": "nsw",
                        }
                    ]
                }
            },
        ),
    ]
    client = HolidayClient()
    async with httpx.AsyncClient() as http:
        docs = await client.fetch_year(http, 2026)
    assert docs is not None
    assert len(docs) == 1
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_fetch_year_skips_call_when_breaker_open():
    settings = MongoSettings(ingest_circuit_breaker_threshold=1)
    breaker = CircuitBreaker("holidays", FakeRedis(), settings=settings)
    await breaker.record_failure()  # threshold=1 -> already open

    client = HolidayClient(settings=settings, circuit_breaker=breaker)
    called = False

    class _TrackingClient:
        async def get(self, *args, **kwargs):
            nonlocal called
            called = True
            return httpx.Response(200, json={"result": {"records": []}})

    docs = await client.fetch_year(_TrackingClient(), 2026)  # type: ignore[arg-type]
    assert docs is None
    assert called is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_year_records_failure_on_breaker(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    respx.get(url__regex=DATASTORE_URL_REGEX).mock(return_value=httpx.Response(500))
    settings = MongoSettings(ingest_max_retries=1)
    breaker = CircuitBreaker("holidays", FakeRedis(), settings=settings)
    client = HolidayClient(settings=settings, circuit_breaker=breaker)

    async with httpx.AsyncClient() as http:
        await client.fetch_year(http, 2026)

    failures = await breaker.redis.get(breaker._failures_key)
    assert failures == "1"
