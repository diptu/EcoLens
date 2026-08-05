import io
import json
import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.service.pipeline.tasks import ingest_aemo_wem

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _PassthroughBreaker:
    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def _bypass_real_breaker(monkeypatch):
    monkeypatch.setattr(
        ingest_aemo_wem, "get_breaker", lambda name: _PassthroughBreaker()
    )


async def test_run_falls_back_to_synthetic_stub_without_live_api_or_cache():
    df = await ingest_aemo_wem.run(lookback_minutes=60)

    assert not df.empty
    assert set(df["region"]) == {"WEM"}


async def test_synthetic_stub_columns_match_the_raw_aemo_wem_dispatch_schema():
    df = ingest_aemo_wem._synthetic_stub(60)

    expected = {
        "ts",
        "region",
        "demand_mw",
        "price_mwh",
        "coal_mw",
        "gas_mw",
        "diesel_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_mw",
        "biomass_mw",
        "total_generation_mw",
        "source",
        "ingested_at",
        "ingest_run_id",
    }
    assert set(df.columns) == expected


# ────────────────────────────────────────────────────────────────────
# Real historical fetch — AEMO WA's current data portal
# ────────────────────────────────────────────────────────────────────


def _demand_json(rows: list[tuple[str, float]]) -> dict:
    """Matches the real
    `OperationalDemandAndWithdrawal_{day}.json` shape — `rows` is
    `(dispatchInterval_iso, operationalDemand)` pairs."""
    return {
        "data": {
            "data": [
                {
                    "dispatchInterval": ts,
                    "asAtTimeStamp": ts,
                    "operationalDemand": demand,
                }
                for ts, demand in rows
            ]
        }
    }


def _price_zip_bytes(rows: list[tuple[str, float]]) -> bytes:
    """Matches the real `ReferenceTradingPrice_{YYYYMMDD}.zip` shape —
    a zip containing one JSON file."""
    payload = {
        "data": {
            "referenceTradingPrices": [
                {
                    "tradingInterval": ts,
                    "referenceTradingPrice": price,
                    "isPublished": True,
                }
                for ts, price in rows
            ]
        }
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ReferenceTradingPrice_2026-08-01.json", json.dumps(payload))
    return buf.getvalue()


class _FakeResponse:
    def __init__(
        self,
        *,
        json_body: dict | None = None,
        content: bytes = b"",
        status_code: int = 200,
    ):
        self._json_body = json_body
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_body


class _FakeClient:
    """Duck-typed stand-in for `httpx.AsyncClient` keyed by exact URL."""

    def __init__(self, responses: dict[str, "_FakeResponse | Exception"]):
        self._responses = responses
        self.requested_urls: list[str] = []

    async def get(self, url: str):
        self.requested_urls.append(url)
        result = self._responses.get(url)
        if isinstance(result, Exception):
            raise result
        if result is None:
            return _FakeResponse(status_code=404)
        return result


async def test_fetch_wem_day_joins_demand_and_price_on_timestamp():
    demand_url = ingest_aemo_wem._DEMAND_URL.format(day="2026-08-01")
    price_url = ingest_aemo_wem._PRICE_URL.format(day_compact="20260801")

    demand_resp = _FakeResponse(
        json_body=_demand_json(
            [
                ("2026-08-01T08:00:00+08:00", 2500.0),
                ("2026-08-01T08:05:00+08:00", 2490.0),  # kept -- no subsampling
                ("2026-08-01T08:30:00+08:00", 2480.0),
            ]
        )
    )
    price_resp = _FakeResponse(
        content=_price_zip_bytes(
            [
                ("2026-08-01T08:00:00+08:00", 95.83),
                ("2026-08-01T08:30:00+08:00", 88.55),
            ]
        )
    )
    client = _FakeClient({demand_url: demand_resp, price_url: price_resp})

    df = await ingest_aemo_wem._fetch_wem_day(client, date(2026, 8, 1))

    # All 3 demand intervals survive; price only exists at :00/:30
    # (its own native resolution), so the :05 row's price is NaN.
    assert len(df) == 3
    assert set(df["region"]) == {"WEM"}
    row_0000 = df[df["demand_mw"] == 2500.0].iloc[0]
    assert row_0000["price_mwh"] == 95.83
    row_0005 = df[df["demand_mw"] == 2490.0].iloc[0]
    assert pd.isna(row_0005["price_mwh"])


async def test_fetch_wem_day_keeps_demand_when_price_fetch_fails():
    demand_url = ingest_aemo_wem._DEMAND_URL.format(day="2026-08-01")
    price_url = ingest_aemo_wem._PRICE_URL.format(day_compact="20260801")

    demand_resp = _FakeResponse(
        json_body=_demand_json([("2026-08-01T08:00:00+08:00", 2500.0)])
    )
    client = _FakeClient({demand_url: demand_resp, price_url: RuntimeError("404")})

    df = await ingest_aemo_wem._fetch_wem_day(client, date(2026, 8, 1))

    assert len(df) == 1
    assert df.iloc[0]["demand_mw"] == 2500.0
    assert pd.isna(df.iloc[0]["price_mwh"])


async def test_fetch_historical_range_skips_a_failing_day_and_keeps_going(monkeypatch):
    calls = []

    async def fake_fetch_wem_day(client, day):
        calls.append(day)
        if day == date(2026, 8, 1):
            raise RuntimeError("simulated failure")
        return pd.DataFrame(
            [
                {
                    "ts": pd.Timestamp("2026-08-02 00:00:00", tz="UTC"),
                    "region": "WEM",
                    "demand_mw": 2500.0,
                    "price_mwh": 90.0,
                }
            ]
        )

    monkeypatch.setattr(ingest_aemo_wem, "_fetch_wem_day", fake_fetch_wem_day)
    monkeypatch.setattr(ingest_aemo_wem.asyncio, "sleep", lambda *_: _noop())

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, tzinfo=timezone.utc)
    df = await ingest_aemo_wem._fetch_historical_range(start, end)

    assert calls == [date(2026, 8, 1), date(2026, 8, 2)]
    assert len(df) == 1
    assert set(df.columns) >= {
        "ts",
        "region",
        "demand_mw",
        "price_mwh",
        "source",
        "ingested_at",
        "ingest_run_id",
    }


async def _noop():
    return None


async def test_run_with_start_and_end_routes_to_the_historical_fetch(monkeypatch):
    called_with = {}

    async def fake_historical_range(start, end):
        called_with["start"] = start
        called_with["end"] = end
        return pd.DataFrame(
            [{"ts": start, "region": "WEM", "demand_mw": 1.0, "price_mwh": 2.0}]
        )

    monkeypatch.setattr(
        ingest_aemo_wem, "_fetch_historical_range", fake_historical_range
    )

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 2, tzinfo=timezone.utc)
    df = await ingest_aemo_wem.run(start=start, end=end)

    assert called_with == {"start": start, "end": end}
    assert len(df) == 1
