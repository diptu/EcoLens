"""Tests for ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import httpx
import pytest
import respx

from conftest import FakeRedis

from ecolens.ingestion.circuit_breaker import CircuitBreaker
from ecolens.ingestion.sources.aemo_wem.client import AEMOWEMClient
from ecolens.ingestion.storage.settings import MongoSettings

BASE = "https://data.wa.aemo.com.au/public/market-data/wemde"


async def _no_sleep(*_args, **_kwargs):
    return None


class TestFetchDayData:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_flow_from_current_directory(self):
        respx.get(f"{BASE}/facilityScada/current/SCADA_2026-07-19.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "facilityScadaDispatchIntervals": [
                            {
                                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                                "code": "BW1_BLUEWATERS_G2",
                                "quantity": 17.94,
                            }
                        ]
                    }
                },
            )
        )
        respx.get(
            f"{BASE}/operationalDemandWithdrawal/dailyFiles/OperationalDemandAndWithdrawal_2026-07-19.json"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "data": [
                            {
                                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                                "operationalDemand": 2326.5,
                            }
                        ]
                    }
                },
            )
        )
        respx.get(
            f"{BASE}/referenceTradingPrice/current/ReferenceTradingPrice_2026-07-19.json"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "referenceTradingPrices": [
                            {
                                "tradingInterval": "2026-07-19T08:00:00+08:00",
                                "referenceTradingPrice": 137.64,
                            }
                        ]
                    }
                },
            )
        )

        client = AEMOWEMClient()
        async with httpx.AsyncClient() as http:
            raw = await client.fetch_day_data(http, date(2026, 7, 19))

        assert raw is not None
        assert raw["scada"][0]["code"] == "BW1_BLUEWATERS_G2"
        assert raw["demand"][0]["operationalDemand"] == 2326.5
        assert raw["price"][0]["referenceTradingPrice"] == 137.64

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_scada_not_published(self):
        respx.get(f"{BASE}/facilityScada/current/SCADA_2026-07-20.json").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{BASE}/facilityScada/previous/FacilityScada_20260720.zip").mock(
            return_value=httpx.Response(404)
        )
        client = AEMOWEMClient()
        async with httpx.AsyncClient() as http:
            raw = await client.fetch_day_data(http, date(2026, 7, 20))
        assert raw is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_demand_missing_yields_empty_list_not_failure(self):
        """The three feeds don't always land at the same time — demand
        lagging shouldn't fail the whole day."""
        respx.get(f"{BASE}/facilityScada/current/SCADA_2026-07-18.json").mock(
            return_value=httpx.Response(
                200, json={"data": {"facilityScadaDispatchIntervals": []}}
            )
        )
        respx.get(
            f"{BASE}/operationalDemandWithdrawal/dailyFiles/OperationalDemandAndWithdrawal_2026-07-18.json"
        ).mock(return_value=httpx.Response(404))
        respx.get(
            f"{BASE}/referenceTradingPrice/current/ReferenceTradingPrice_2026-07-18.json"
        ).mock(
            return_value=httpx.Response(
                200, json={"data": {"referenceTradingPrices": []}}
            )
        )
        client = AEMOWEMClient()
        async with httpx.AsyncClient() as http:
            raw = await client.fetch_day_data(http, date(2026, 7, 18))
        assert raw is not None
        assert raw["demand"] == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_previous_zip_with_different_prefix(self):
        """Regression: facilityScada's `previous/` zip filename prefix
        is `FacilityScada_{date}.zip`, NOT `SCADA_{date}.zip` (the
        current/JSON prefix) — a real bug caught via live testing."""
        respx.get(f"{BASE}/facilityScada/current/SCADA_2026-07-18.json").mock(
            return_value=httpx.Response(404)
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "SCADA_2026-07-18.json",
                '{"data": {"facilityScadaDispatchIntervals": [{"dispatchInterval": "x", "code": "Y", "quantity": 1.0}]}}',
            )
        respx.get(f"{BASE}/facilityScada/previous/FacilityScada_20260718.zip").mock(
            return_value=httpx.Response(200, content=buf.getvalue())
        )
        respx.get(
            f"{BASE}/operationalDemandWithdrawal/dailyFiles/OperationalDemandAndWithdrawal_2026-07-18.json"
        ).mock(return_value=httpx.Response(200, json={"data": {"data": []}}))
        respx.get(
            f"{BASE}/referenceTradingPrice/current/ReferenceTradingPrice_2026-07-18.json"
        ).mock(
            return_value=httpx.Response(
                200, json={"data": {"referenceTradingPrices": []}}
            )
        )
        client = AEMOWEMClient()
        async with httpx.AsyncClient() as http:
            raw = await client.fetch_day_data(http, date(2026, 7, 18))
        assert raw is not None
        assert raw["scada"][0]["code"] == "Y"

    @pytest.mark.asyncio
    @respx.mock
    async def test_price_missing_from_both_current_and_previous(self):
        respx.get(f"{BASE}/facilityScada/current/SCADA_2026-07-18.json").mock(
            return_value=httpx.Response(
                200, json={"data": {"facilityScadaDispatchIntervals": []}}
            )
        )
        respx.get(
            f"{BASE}/operationalDemandWithdrawal/dailyFiles/OperationalDemandAndWithdrawal_2026-07-18.json"
        ).mock(return_value=httpx.Response(200, json={"data": {"data": []}}))
        respx.get(
            f"{BASE}/referenceTradingPrice/current/ReferenceTradingPrice_2026-07-18.json"
        ).mock(return_value=httpx.Response(404))
        respx.get(
            f"{BASE}/referenceTradingPrice/previous/ReferenceTradingPrice_20260718.zip"
        ).mock(return_value=httpx.Response(404))
        client = AEMOWEMClient()
        async with httpx.AsyncClient() as http:
            raw = await client.fetch_day_data(http, date(2026, 7, 18))
        assert raw is not None
        assert raw["price"] == []


class TestRetryAndCircuitBreaker:
    @pytest.mark.asyncio
    @respx.mock
    async def test_transient_500_is_retried_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        route = respx.get(f"{BASE}/facilityScada/current/SCADA_2026-07-19.json")
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(200, json={"data": {"facilityScadaDispatchIntervals": []}}),
        ]
        respx.get(
            f"{BASE}/operationalDemandWithdrawal/dailyFiles/OperationalDemandAndWithdrawal_2026-07-19.json"
        ).mock(return_value=httpx.Response(200, json={"data": {"data": []}}))
        respx.get(
            f"{BASE}/referenceTradingPrice/current/ReferenceTradingPrice_2026-07-19.json"
        ).mock(
            return_value=httpx.Response(
                200, json={"data": {"referenceTradingPrices": []}}
            )
        )

        client = AEMOWEMClient()
        async with httpx.AsyncClient() as http:
            raw = await client.fetch_day_data(http, date(2026, 7, 19))
        assert raw is not None
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_exhausted_retries_raise_and_record_breaker_failure(
        self, monkeypatch
    ):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        respx.get(f"{BASE}/facilityScada/current/SCADA_2026-07-19.json").mock(
            return_value=httpx.Response(500)
        )
        settings = MongoSettings(ingest_max_retries=1)
        breaker = CircuitBreaker("aemo_wem", FakeRedis(), settings=settings)
        client = AEMOWEMClient(settings=settings, circuit_breaker=breaker)

        async with httpx.AsyncClient() as http:
            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_day_data(http, date(2026, 7, 19))

        failures = await breaker.redis.get(breaker._failures_key)
        assert failures == "1"

    @pytest.mark.asyncio
    async def test_skips_all_calls_when_breaker_open(self):
        settings = MongoSettings(ingest_circuit_breaker_threshold=1)
        breaker = CircuitBreaker("aemo_wem", FakeRedis(), settings=settings)
        await breaker.record_failure()  # threshold=1 -> already open

        client = AEMOWEMClient(settings=settings, circuit_breaker=breaker)
        called = False

        class _TrackingClient:
            async def get(self, *args, **kwargs):
                nonlocal called
                called = True
                return httpx.Response(200, json={})

        from ecolens.ingestion.circuit_breaker import CircuitBreakerOpen

        with pytest.raises(CircuitBreakerOpen):
            await client.fetch_day_data(_TrackingClient(), date(2026, 7, 19))  # type: ignore[arg-type]
        assert called is False
