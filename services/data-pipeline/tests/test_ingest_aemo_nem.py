import io
import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.service.pipeline.tasks import ingest_aemo_nem

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
        ingest_aemo_nem, "get_breaker", lambda name: _PassthroughBreaker()
    )


async def test_run_falls_back_to_synthetic_stub_without_live_api_or_cache():
    # No live AEMO endpoint reachable as designed (the real fetch always
    # returns None -- see _try_live_api's docstring), and no
    # /data/raw/aemo/nem cache dir on this machine -> synthetic stub path.
    df = await ingest_aemo_nem.run(lookback_minutes=15)

    assert not df.empty
    assert set(df["region"]) == set(ingest_aemo_nem.REGIONS)


async def test_synthetic_stub_columns_match_the_raw_aemo_nem_dispatch_schema():
    df = ingest_aemo_nem._synthetic_stub(15)

    expected = {
        "ts",
        "region",
        "demand_mw",
        "price_mwh",
        "coal_mw",
        "gas_mw",
        "hydro_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_mw",
        "net_import_mw",
        "source",
        "ingested_at",
        "ingest_run_id",
    }
    assert set(df.columns) == expected


# ────────────────────────────────────────────────────────────────────
# Real historical fetch — NEMWeb Archive path
# ────────────────────────────────────────────────────────────────────


def _dispatchis_csv(
    settlement_date: str, region: str, demand: float, rrp: float
) -> str:
    """A minimal but structurally real AEMO MMS CSV: one REGIONSUM row
    (TOTALDEMAND) and one PRICE row (RRP) for one region/interval —
    exact column positions match a real downloaded sample (see
    `_parse_dispatchis_csv`'s own docstring), just trimmed to the
    columns this parser actually reads."""
    header = (
        "I,DISPATCH,REGIONSUM,9,SETTLEMENTDATE,RUNNO,REGIONID,DISPATCHINTERVAL,"
        "INTERVENTION,TOTALDEMAND\n"
    )
    demand_row = f'D,DISPATCH,REGIONSUM,9,"{settlement_date}",1,{region},1,0,{demand}\n'
    price_header = (
        "I,DISPATCH,PRICE,5,SETTLEMENTDATE,RUNNO,REGIONID,DISPATCHINTERVAL,"
        "INTERVENTION,RRP\n"
    )
    price_row = f'D,DISPATCH,PRICE,5,"{settlement_date}",1,{region},1,0,{rrp}\n'
    return header + demand_row + price_header + price_row


def _build_archive_zip(intervals: dict[str, list[str]]) -> bytes:
    """Build a real zip-of-zips matching NEMWeb's actual Archive
    structure: an outer zip containing one nested zip per dispatch
    interval, each holding one CSV. `intervals` maps a nested zip's
    embedded-minute-mark filename stem (e.g.
    `PUBLIC_DISPATCHIS_202608010030_1.zip`) to the list of CSV lines
    (already-built via `_dispatchis_csv`) it should contain."""
    outer_buf = io.BytesIO()
    with zipfile.ZipFile(outer_buf, "w") as outer:
        for name, csv_texts in intervals.items():
            inner_buf = io.BytesIO()
            with zipfile.ZipFile(inner_buf, "w") as inner:
                inner.writestr(name.replace(".zip", ".CSV"), "".join(csv_texts))
            outer.writestr(name, inner_buf.getvalue())
    return outer_buf.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Duck-typed stand-in for `httpx.AsyncClient` — `_fetch_archive_day`
    only ever calls `.get(url)` on it."""

    def __init__(self, responses: dict[str, bytes | Exception]):
        self._responses = responses
        self.requested_urls: list[str] = []

    async def get(self, url: str):
        self.requested_urls.append(url)
        result = self._responses.get(url)
        if isinstance(result, Exception):
            raise result
        if result is None:
            return _FakeResponse(b"", status_code=404)
        return _FakeResponse(result)


def test_interval_minute_extracts_the_minute_component():
    name = "PUBLIC_DISPATCHIS_202608010030_0000000530265329.zip"
    assert ingest_aemo_nem._interval_minute(name) == 30

    name_05 = "PUBLIC_DISPATCHIS_202608010005_0000000530262456.zip"
    assert ingest_aemo_nem._interval_minute(name_05) == 5


def test_interval_minute_returns_none_for_an_unrecognized_name():
    assert ingest_aemo_nem._interval_minute("not_a_real_filename.zip") is None


def test_parse_dispatchis_csv_extracts_demand_and_price_per_region():
    text = _dispatchis_csv("2026/08/01 00:30:00", "NSW1", 8898.91, 89.87989)

    rows = ingest_aemo_nem._parse_dispatchis_csv(text)

    assert len(rows) == 1
    row = rows[0]
    assert row["region"] == "NSW1"
    assert row["demand_mw"] == 8898.91
    assert row["price_mwh"] == 89.87989
    # NEM settlement dates are AEST (UTC+10, no DST) -- 00:30 AEST is
    # 14:30 UTC the *previous* day.
    assert row["ts"] == pd.Timestamp("2026-07-31 14:30:00", tz="UTC")


def test_parse_dispatchis_csv_ignores_unrelated_tables():
    text = (
        "C,NEMP.WORLD,DISPATCHIS,AEMO,PUBLIC,2026/08/01,00:00:10,1,DISPATCHIS,2\n"
        "I,DISPATCH,CASE_SOLUTION,2,SETTLEMENTDATE,RUNNO\n"
        'D,DISPATCH,CASE_SOLUTION,2,"2026/08/01 00:30:00",1\n'
    )
    assert ingest_aemo_nem._parse_dispatchis_csv(text) == []


async def test_fetch_archive_day_samples_only_the_30_min_marks(monkeypatch):
    csv_0000 = _dispatchis_csv("2026/08/01 00:00:00", "NSW1", 8000.0, 50.0)
    csv_0005 = _dispatchis_csv("2026/08/01 00:05:00", "NSW1", 8100.0, 51.0)
    csv_0030 = _dispatchis_csv("2026/08/01 00:30:00", "NSW1", 8200.0, 52.0)
    archive_bytes = _build_archive_zip(
        {
            "PUBLIC_DISPATCHIS_202608010000_1.zip": [csv_0000],
            "PUBLIC_DISPATCHIS_202608010005_2.zip": [csv_0005],
            "PUBLIC_DISPATCHIS_202608010030_3.zip": [csv_0030],
        }
    )
    url = ingest_aemo_nem._ARCHIVE_URL.format(day="20260801")
    client = _FakeClient({url: archive_bytes})

    df = await ingest_aemo_nem._fetch_archive_day(client, date(2026, 8, 1))

    # Only the :00 and :30 marks are sampled -- :05 is skipped.
    assert len(df) == 2
    assert set(df["demand_mw"]) == {8000.0, 8200.0}


async def test_fetch_historical_range_skips_a_failing_day_and_keeps_going(monkeypatch):
    calls = []

    async def fake_fetch_archive_day(client, day):
        calls.append(day)
        if day == date(2026, 8, 1):
            raise RuntimeError("simulated 404 — outside retention")
        return pd.DataFrame(
            [
                {
                    "ts": pd.Timestamp("2026-08-01 14:00:00", tz="UTC"),
                    "region": "NSW1",
                    "demand_mw": 9000.0,
                    "price_mwh": 60.0,
                }
            ]
        )

    monkeypatch.setattr(ingest_aemo_nem, "_fetch_archive_day", fake_fetch_archive_day)
    monkeypatch.setattr(ingest_aemo_nem.asyncio, "sleep", lambda *_: _noop())

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, tzinfo=timezone.utc)
    df = await ingest_aemo_nem._fetch_historical_range(start, end)

    # Both days were attempted (the failing one didn't stop the loop),
    # and the one good day's rows made it into the result.
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
            [{"ts": start, "region": "NSW1", "demand_mw": 1.0, "price_mwh": 2.0}]
        )

    monkeypatch.setattr(
        ingest_aemo_nem, "_fetch_historical_range", fake_historical_range
    )

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 2, tzinfo=timezone.utc)
    df = await ingest_aemo_nem.run(start=start, end=end)

    assert called_with == {"start": start, "end": end}
    assert len(df) == 1
