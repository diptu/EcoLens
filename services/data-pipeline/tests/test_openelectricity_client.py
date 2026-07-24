"""Tests for ecolens.ingestion.sources.openelectricity.client.OpenElectricityClient."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from conftest import FakeRedis

from ecolens.ingestion.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from ecolens.ingestion.sources.openelectricity.client import OpenElectricityClient
from ecolens.ingestion.storage.settings import MongoSettings


async def _no_sleep(*_args, **_kwargs):
    return None


class TestParseHttpResponse:
    """`columns` is a small static grouping dict, `data` is [ts, value]
    pairs — NOT a per-row column schema. This was a real bug (fixed
    earlier this session): treating `columns` as a zip-able header
    silently produced ts=None/mw=None on every row."""

    def test_power_metric_extracts_fuel_from_columns_dict(self):
        client = OpenElectricityClient(api_key="test")
        body = {
            "data": [
                {
                    "results": [
                        {
                            "columns": {"fueltech": "wind"},
                            "data": [["2026-07-20T10:00:00+10:00", 100.0]],
                        }
                    ]
                }
            ]
        }
        df = client._parse_http_response(body, "NEM", "power")
        assert len(df) == 1
        assert df.iloc[0]["ts"] == "2026-07-20T10:00:00+10:00"
        assert df.iloc[0]["fuel"] == "wind"
        assert df.iloc[0]["mw"] == 100.0

    def test_scalar_metric_has_no_fuel_column(self):
        client = OpenElectricityClient(api_key="test")
        body = {
            "data": [
                {
                    "results": [
                        {"columns": {}, "data": [["2026-07-20T10:00:00+10:00", 85.0]]}
                    ]
                }
            ]
        }
        df = client._parse_http_response(body, "NEM", "price")
        assert df.iloc[0]["price_mwh"] == 85.0

    def test_empty_response_yields_empty_frame(self):
        client = OpenElectricityClient(api_key="test")
        df = client._parse_http_response({"data": []}, "NEM", "power")
        assert df.empty

    def test_multiple_series_and_rows(self):
        client = OpenElectricityClient(api_key="test")
        body = {
            "data": [
                {
                    "results": [
                        {
                            "columns": {"fueltech": "wind"},
                            "data": [
                                ["2026-07-20T10:00:00+10:00", 100.0],
                                ["2026-07-20T10:05:00+10:00", 105.0],
                            ],
                        },
                        {
                            "columns": {"fueltech": "solar_utility"},
                            "data": [["2026-07-20T10:00:00+10:00", 50.0]],
                        },
                    ]
                }
            ]
        }
        df = client._parse_http_response(body, "NEM", "power")
        assert len(df) == 3
        assert set(df["fuel"]) == {"wind", "solar_utility"}


class TestParseFacilityResponse:
    def test_maps_fields_and_falls_back_capacity(self):
        client = OpenElectricityClient(api_key="test")
        body = {
            "data": [
                {
                    "code": "BAYSW1",
                    "name": "Bayswater Unit 1",
                    "region_id": "NSW1",
                    "fuel_type": "coal_black",
                    "capacity_registered": 660.0,
                    "capacity_maximum": None,
                }
            ]
        }
        df = client._parse_facility_response(body, "NEM")
        row = df.iloc[0]
        assert row["facility_id"] == "BAYSW1"
        assert row["network"] == "NEM"
        assert row["region"] == "NSW1"
        # capacity_maximum was null -> falls back to capacity_registered
        assert row["capacity_maximum_mw"] == 660.0
        assert row["source"] == "openelectricity"
        assert row["schema_version"] == "1.0"

    def test_empty_facilities_list(self):
        client = OpenElectricityClient(api_key="test")
        df = client._parse_facility_response({"data": []}, "NEM")
        assert df.empty


class TestReshapeSdkResponse:
    """Pure reshape function — exercised directly since the optional
    `openelectricity` SDK package isn't installed in this environment."""

    def test_power_melts_wide_sdk_frame_to_long(self):
        import pandas as pd

        client = OpenElectricityClient(api_key="test")
        sdk_df = pd.DataFrame(
            {"wind": [100.0], "solar_utility": [50.0]},
            index=pd.Index(["2026-07-20T10:00:00+10:00"], name="interval"),
        )
        long = client._reshape_sdk_response(sdk_df, "NEM", "power")
        assert set(long["fuel"]) == {"wind", "solar_utility"}
        assert set(long.columns) == {"ts", "region", "fuel", "mw"}

    def test_scalar_metric_renames_single_column(self):
        import pandas as pd

        client = OpenElectricityClient(api_key="test")
        sdk_df = pd.DataFrame(
            {"price": [85.0]}, index=pd.Index(["2026-07-20T10:00:00+10:00"], name="ts")
        )
        out = client._reshape_sdk_response(sdk_df, "NEM", "price")
        assert out.iloc[0]["price_mwh"] == 85.0
        assert out.iloc[0]["region"] == "NEM"

    def test_unknown_metric_returns_empty_frame(self):
        import pandas as pd

        client = OpenElectricityClient(api_key="test")
        out = client._reshape_sdk_response(pd.DataFrame(), "NEM", "not_a_real_metric")
        assert out.empty

    @pytest.mark.parametrize(
        ("metric", "value_col"),
        [
            ("demand", "demand_mw"),
            ("emissions", "emissions_intensity_kgco2e_per_mwh"),
            ("renewable_proportion", "renewable_proportion"),
            ("market_value", "market_value"),
        ],
    )
    def test_scalar_metric_variants(self, metric, value_col):
        import pandas as pd

        client = OpenElectricityClient(api_key="test")
        sdk_df = pd.DataFrame(
            {metric: [42.0]}, index=pd.Index(["2026-07-20T10:00:00+10:00"], name="ts")
        )
        out = client._reshape_sdk_response(sdk_df, "NEM", metric)
        assert out.iloc[0][value_col] == 42.0

    def test_curtailment_melts_wide_sdk_frame_to_long(self):
        import pandas as pd

        client = OpenElectricityClient(api_key="test")
        sdk_df = pd.DataFrame(
            {"solar_utility": [5.0]},
            index=pd.Index(["2026-07-20T10:00:00+10:00"], name="ts"),
        )
        out = client._reshape_sdk_response(sdk_df, "NEM", "curtailment")
        assert out.iloc[0]["curtailment_mw"] == 5.0
        assert out.iloc[0]["fuel"] == "solar_utility"

    @pytest.mark.parametrize(
        "metric", ["interconnector_imports", "interconnector_exports"]
    )
    def test_interconnector_flow_variants(self, metric):
        import pandas as pd

        client = OpenElectricityClient(api_key="test")
        sdk_df = pd.DataFrame(
            {"flow": [10.0]}, index=pd.Index(["2026-07-20T10:00:00+10:00"], name="ts")
        )
        out = client._reshape_sdk_response(sdk_df, "NEM", metric)
        assert out.iloc[0]["flow_mw"] == 10.0
        assert out.iloc[0]["flow_type"] == metric


class TestNoApiKey:
    def test_missing_api_key_still_constructs_with_empty_headers(self):
        client = OpenElectricityClient(api_key=None)
        assert client.headers == {}


class TestFetchWithHttp:
    @pytest.mark.asyncio
    @respx.mock
    async def test_power_uses_data_endpoint_with_secondary_grouping(self):
        route = respx.get(
            "https://api.openelectricity.org.au/v4/data/network/NEM",
            params={"metrics": "power"},
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "results": [
                                {
                                    "columns": {"fueltech": "wind"},
                                    "data": [["2026-07-20T10:00:00+10:00", 100.0]],
                                }
                            ]
                        }
                    ]
                },
            )
        )
        client = OpenElectricityClient(api_key="test", use_sdk=False)
        async with httpx.AsyncClient() as http:
            df = await client.fetch_metric(
                http,
                "NEM",
                "power",
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            )
        assert route.called
        request = route.calls[0].request
        assert "secondary_grouping=fueltech" in str(request.url)
        assert df.iloc[0]["mw"] == 100.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_price_uses_market_endpoint(self):
        route = respx.get(
            "https://api.openelectricity.org.au/v4/market/network/NEM"
        ).mock(return_value=httpx.Response(200, json={"data": []}))
        client = OpenElectricityClient(api_key="test", use_sdk=False)
        async with httpx.AsyncClient() as http:
            await client.fetch_metric(
                http,
                "NEM",
                "price",
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            )
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_metric_tries_sdk_first_then_falls_back_to_http(
        self, monkeypatch
    ):
        respx.get("https://api.openelectricity.org.au/v4/data/network/NEM").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = OpenElectricityClient(api_key="test", use_sdk=False)
        client.use_sdk = True  # simulate the SDK being importable

        async def fake_sdk_fetch(*args, **kwargs):
            return None  # SDK unavailable/errored -> should fall back to HTTP

        monkeypatch.setattr(client, "_fetch_with_sdk", fake_sdk_fetch)
        async with httpx.AsyncClient() as http:
            df = await client.fetch_metric(
                http,
                "NEM",
                "power",
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            )
        assert df.empty

    @pytest.mark.asyncio
    async def test_fetch_metric_returns_sdk_result_directly_when_available(
        self, monkeypatch
    ):
        import pandas as pd

        client = OpenElectricityClient(api_key="test", use_sdk=False)
        client.use_sdk = True
        sdk_result = pd.DataFrame([{"ts": "x", "region": "NEM", "price_mwh": 1.0}])

        async def fake_sdk_fetch(*args, **kwargs):
            return sdk_result

        monkeypatch.setattr(client, "_fetch_with_sdk", fake_sdk_fetch)
        async with httpx.AsyncClient() as http:
            df = await client.fetch_metric(
                http,
                "NEM",
                "price",
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            )
        assert df is sdk_result

    @pytest.mark.asyncio
    @respx.mock
    async def test_interconnector_imports_translates_to_flow_imports_api_name(self):
        route = respx.get(
            "https://api.openelectricity.org.au/v4/market/network/NEM",
            params={"metrics": "flow_imports"},
        ).mock(return_value=httpx.Response(200, json={"data": []}))
        client = OpenElectricityClient(api_key="test", use_sdk=False)
        async with httpx.AsyncClient() as http:
            await client.fetch_metric(
                http,
                "NEM",
                "interconnector_imports",
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            )
        assert route.called


class TestRetryAndCircuitBreaker:
    @pytest.mark.asyncio
    @respx.mock
    async def test_transient_500_is_retried_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        route = respx.get("https://api.openelectricity.org.au/v4/data/network/NEM")
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(200, json={"data": []}),
        ]
        client = OpenElectricityClient(api_key="test", use_sdk=False)
        async with httpx.AsyncClient() as http:
            df = await client.fetch_metric(
                http,
                "NEM",
                "power",
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            )
        assert df.empty
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_exhausted_retries_raise_and_record_breaker_failure(
        self, monkeypatch
    ):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        respx.get("https://api.openelectricity.org.au/v4/data/network/NEM").mock(
            return_value=httpx.Response(500)
        )
        settings = MongoSettings(ingest_max_retries=1)
        breaker = CircuitBreaker("openelectricity", FakeRedis(), settings=settings)
        client = OpenElectricityClient(
            api_key="test", use_sdk=False, settings=settings, circuit_breaker=breaker
        )

        async with httpx.AsyncClient() as http:
            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_metric(
                    http,
                    "NEM",
                    "power",
                    datetime(2026, 7, 20, tzinfo=timezone.utc),
                    datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
                )

        failures = await breaker.redis.get(breaker._failures_key)
        assert failures == "1"

    @pytest.mark.asyncio
    async def test_skips_call_when_breaker_open(self):
        settings = MongoSettings(ingest_circuit_breaker_threshold=1)
        breaker = CircuitBreaker("openelectricity", FakeRedis(), settings=settings)
        await breaker.record_failure()  # threshold=1 -> already open

        client = OpenElectricityClient(
            api_key="test", use_sdk=False, settings=settings, circuit_breaker=breaker
        )
        called = False

        class _TrackingClient:
            async def get(self, *args, **kwargs):
                nonlocal called
                called = True
                return httpx.Response(200, json={"data": []})

        with pytest.raises(CircuitBreakerOpen):
            await client.fetch_metric(
                _TrackingClient(),  # type: ignore[arg-type]
                "NEM",
                "power",
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
            )
        assert called is False
