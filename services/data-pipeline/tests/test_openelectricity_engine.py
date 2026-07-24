"""End-to-end (mocked HTTP) tests for OpenElectricityFetcher/OpenElectricityFacilityFetcher."""

from __future__ import annotations

import httpx
import pytest
import respx

from ecolens.ingestion.sources.openelectricity import (
    OpenElectricityFacilityFetcher,
    OpenElectricityFetcher,
)

METRIC_VALUES = {
    "power": 100.0,
    "price": 85.0,
    "demand": 25000.0,
    "emissions": 1200.0,
    "curtailment_solar_utility": 0.0,
    "curtailment_wind": 0.0,
    "renewable_proportion": 25.0,
    "flow_imports": 500.0,
    "flow_exports": 500.0,
    "market_value": 2000.0,
}


def _mock_oe_response(request: httpx.Request) -> httpx.Response:
    metric = httpx.QueryParams(request.url.query).get("metrics")
    value = METRIC_VALUES.get(metric, 0.0)
    columns = {"fueltech": "wind"} if metric == "power" else {}
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "network_code": "NEM",
                    "metric": metric,
                    "results": [
                        {
                            "name": f"{metric}_total",
                            "columns": columns,
                            "data": [["2026-07-20T10:00:00+10:00", value]],
                        }
                    ],
                }
            ]
        },
    )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_merges_all_metrics_into_one_document_per_network():
    respx.get(
        url__regex=r"https://api\.openelectricity\.org\.au/v4/(data|market)/network/.*"
    ).mock(side_effect=_mock_oe_response)

    fetcher = OpenElectricityFetcher(api_key="test-key", use_sdk=False)
    async with httpx.AsyncClient() as client:
        results = await fetcher.fetch(client)

    assert len(results) == 2  # one row per network (NEM, WEM)
    row = results[0]
    assert row["wind_mw"] == 100.0
    assert row["price_mwh"] == 85.0
    assert row["demand_mw"] == 25000.0
    assert row["source"] == "openelectricity"
    assert row["schema_version"] == "1.0"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_only_queries_requested_networks():
    route = respx.get(
        url__regex=r"https://api\.openelectricity\.org\.au/v4/(data|market)/network/.*"
    ).mock(side_effect=_mock_oe_response)

    fetcher = OpenElectricityFetcher(api_key="test-key", use_sdk=False)
    async with httpx.AsyncClient() as client:
        results = await fetcher.fetch(client, networks=["NEM"])

    assert len(results) == 1
    assert results[0]["network_code"] == "NEM"
    assert all("/NEM" in str(call.request.url) for call in route.calls)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_survives_one_metric_failing(monkeypatch):
    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)

    def flaky(request: httpx.Request) -> httpx.Response:
        metric = httpx.QueryParams(request.url.query).get("metrics")
        if metric == "power":
            return httpx.Response(500, json={"error": "boom"})
        return _mock_oe_response(request)

    respx.get(
        url__regex=r"https://api\.openelectricity\.org\.au/v4/(data|market)/network/.*"
    ).mock(side_effect=flaky)

    fetcher = OpenElectricityFetcher(api_key="test-key", use_sdk=False)
    async with httpx.AsyncClient() as client:
        results = await fetcher.fetch(client, networks=["NEM"])

    # power failed -> falls back to minimal_doc using whatever else succeeded.
    assert len(results) == 1
    assert results[0]["price_mwh"] == 85.0
    assert results[0]["total_generation_mw"] is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_skips_metrics_unsupported_by_network(monkeypatch):
    from ecolens.ingestion.sources.openelectricity import engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "NETWORK_CAPABILITIES",
        {"NEM": {"power": True, "price": False}},
    )
    route = respx.get(
        url__regex=r"https://api\.openelectricity\.org\.au/v4/(data|market)/network/.*"
    ).mock(side_effect=_mock_oe_response)

    fetcher = OpenElectricityFetcher(api_key="test-key", use_sdk=False)
    async with httpx.AsyncClient() as client:
        await fetcher.fetch(client, networks=["NEM"], metrics=["power", "price"])

    # Only "power" should have been requested — "price" is unsupported.
    called_metrics = {
        httpx.QueryParams(c.request.url.query).get("metrics") for c in route.calls
    }
    assert called_metrics == {"power"}


@pytest.mark.asyncio
async def test_fetch_facilities_survives_one_network_failing(monkeypatch):
    from ecolens.ingestion.sources.openelectricity.client import OpenElectricityClient

    async def flaky_fetch(self, client, network):
        if network == "NEM":
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(OpenElectricityClient, "fetch_facilities_raw", flaky_fetch)
    fetcher = OpenElectricityFacilityFetcher(api_key="test-key")
    async with httpx.AsyncClient() as client:
        facilities = await fetcher.fetch_facilities(client, networks=["NEM", "WEM"])
    assert facilities == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_facilities():
    respx.get("https://api.openelectricity.org.au/v4/facilities/NEM").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"code": "BAYSW1", "name": "Bayswater Unit 1", "region_id": "NSW1"}
                ]
            },
        )
    )
    respx.get("https://api.openelectricity.org.au/v4/facilities/WEM").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    fetcher = OpenElectricityFacilityFetcher(api_key="test-key")
    async with httpx.AsyncClient() as client:
        facilities = await fetcher.fetch_facilities(client)

    assert len(facilities) == 1
    assert facilities[0]["facility_id"] == "BAYSW1"
