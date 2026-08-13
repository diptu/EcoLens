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


async def test_fetch_archive_day_keeps_every_5_min_interval(monkeypatch):
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

    # No subsampling -- every real interval in the archive, including :05, survives.
    assert len(df) == 3
    assert set(df["demand_mw"]) == {8000.0, 8100.0, 8200.0}


async def test_fetch_historical_range_skips_a_failing_day_and_keeps_going(monkeypatch):
    calls = []
    mmsdm_calls = []

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

    async def fake_fetch_mmsdm_day(client, day):
        # The MMSDM fallback is real network I/O -- mocked here (not just
        # left unmocked) so this stays a real, fast, network-free unit
        # test rather than silently hitting the live archive for a day
        # that's genuinely outside it (a *future* date, in this test).
        mmsdm_calls.append(day)
        raise RuntimeError("simulated MMSDM failure too — this day is unrecoverable")

    monkeypatch.setattr(ingest_aemo_nem, "_fetch_archive_day", fake_fetch_archive_day)
    monkeypatch.setattr(ingest_aemo_nem, "_fetch_mmsdm_day", fake_fetch_mmsdm_day)
    monkeypatch.setattr(ingest_aemo_nem.asyncio, "sleep", lambda *_: _noop())

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, tzinfo=timezone.utc)
    df = await ingest_aemo_nem._fetch_historical_range(start, end)

    # Both days were attempted (the failing one didn't stop the loop),
    # the MMSDM fallback was tried for the failing day specifically (and
    # also failed, so that day is genuinely dropped), and the one good
    # day's rows made it into the result.
    assert calls == [date(2026, 8, 1), date(2026, 8, 2)]
    assert mmsdm_calls == [date(2026, 8, 1)]
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


async def test_fetch_historical_range_uses_mmsdm_when_archive_day_fails(monkeypatch):
    """The real end-to-end shape this fallback exists for: the cheap
    per-day Archive fetch 404s (outside its real retention window), and
    the MMSDM fallback's own rows for that day still make it into the
    final result."""

    async def failing_archive_day(client, day):
        raise RuntimeError("simulated 404 — outside retention")

    async def fake_mmsdm_day(client, day):
        return pd.DataFrame(
            [
                {
                    "ts": pd.Timestamp("2020-01-15 14:00:00", tz="UTC"),
                    "region": "NSW1",
                    "demand_mw": 7500.0,
                    "price_mwh": 45.0,
                }
            ]
        )

    monkeypatch.setattr(ingest_aemo_nem, "_fetch_archive_day", failing_archive_day)
    monkeypatch.setattr(ingest_aemo_nem, "_fetch_mmsdm_day", fake_mmsdm_day)
    monkeypatch.setattr(ingest_aemo_nem.asyncio, "sleep", lambda *_: _noop())

    start = datetime(2020, 1, 15, tzinfo=timezone.utc)
    end = datetime(2020, 1, 15, tzinfo=timezone.utc)
    df = await ingest_aemo_nem._fetch_historical_range(start, end)

    assert len(df) == 1
    assert df.iloc[0]["region"] == "NSW1"
    assert df.iloc[0]["demand_mw"] == 7500.0


async def _noop():
    return None


# ────────────────────────────────────────────────────────────────────
# MMSDM fallback — deeper real historical path (2026-08-12)
# ────────────────────────────────────────────────────────────────────


def test_mmsdm_table_url_uses_the_old_pattern_before_2025():
    url = ingest_aemo_nem._mmsdm_table_url("DISPATCHREGIONSUM", 2020, 1)
    assert url == (
        "https://www.nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM/"
        "2020/MMSDM_2020_01/MMSDM_Historical_Data_SQLLoader/DATA/"
        "PUBLIC_DVD_DISPATCHREGIONSUM_202001010000.zip"
    )


def test_mmsdm_table_url_uses_the_new_pattern_from_2025_onward():
    url = ingest_aemo_nem._mmsdm_table_url("DISPATCHPRICE", 2025, 7)
    assert url == (
        "https://www.nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM/"
        "2025/MMSDM_2025_07/MMSDM_Historical_Data_SQLLoader/DATA/"
        "PUBLIC_ARCHIVE%23DISPATCHPRICE%23FILE01%23202507010000.zip"
    )


def test_mmsdm_table_url_real_boundary_is_2024_08_not_2025():
    """Regression: the real cutoff (binary-searched live 2026-08-13
    against `nemweb.com.au` -- `MMSDM_2024_07`'s old-pattern URL 200s,
    `MMSDM_2024_08`'s doesn't but its new-pattern URL does) is mid-2024,
    not "any year >= 2025" -- the bug this test guards against silently
    built a 404-guaranteed URL for every real Aug-Dec 2024 NEM backfill
    request before this fix."""
    july = ingest_aemo_nem._mmsdm_table_url("DISPATCHREGIONSUM", 2024, 7)
    assert july.endswith("PUBLIC_DVD_DISPATCHREGIONSUM_202407010000.zip")

    august = ingest_aemo_nem._mmsdm_table_url("DISPATCHREGIONSUM", 2024, 8)
    assert august.endswith(
        "PUBLIC_ARCHIVE%23DISPATCHREGIONSUM%23FILE01%23202408010000.zip"
    )


def _mmsdm_regionsum_csv(rows: list[tuple[str, str, float]]) -> str:
    """A minimal but structurally real MMSDM `DISPATCHREGIONSUM` monthly
    CSV — same real column layout as a downloaded 2020-01 sample
    (`SETTLEMENTDATE` at index 4, `REGIONID` at index 6, `TOTALDEMAND` at
    index 9), trimmed to just those columns."""
    lines = [
        "C,SETP.WORLD,DVD_DISPATCHREGIONSUM,AEMO,PUBLIC,2020/02/07,00:35:06,1,,1\n",
        "I,DISPATCH,REGIONSUM,4,SETTLEMENTDATE,RUNNO,REGIONID,DISPATCHINTERVAL,"
        "INTERVENTION,TOTALDEMAND\n",
    ]
    for settlement_date, region, demand in rows:
        lines.append(f'D,DISPATCH,REGIONSUM,4,"{settlement_date}",1,{region},1,0,{demand}\n')
    return "".join(lines)


def _mmsdm_price_csv(rows: list[tuple[str, str, float]]) -> str:
    lines = [
        "C,SETP.WORLD,DVD_DISPATCHPRICE,AEMO,PUBLIC,2020/02/07,00:35:05,1,,1\n",
        "I,DISPATCH,PRICE,1,SETTLEMENTDATE,RUNNO,REGIONID,DISPATCHINTERVAL,"
        "INTERVENTION,RRP\n",
    ]
    for settlement_date, region, rrp in rows:
        lines.append(f'D,DISPATCH,PRICE,1,"{settlement_date}",1,{region},1,0,{rrp}\n')
    return "".join(lines)


def test_parse_mmsdm_regionsum_and_price_merges_by_settlement_and_region():
    regionsum = _mmsdm_regionsum_csv(
        [
            ("2020/01/15 00:05:00", "NSW1", 7245.31),
            ("2020/01/15 00:05:00", "QLD1", 6095.75),
        ]
    )
    price = _mmsdm_price_csv(
        [
            ("2020/01/15 00:05:00", "NSW1", 49.00916),
            ("2020/01/15 00:05:00", "QLD1", 38.5),
        ]
    )

    rows = ingest_aemo_nem._parse_mmsdm_regionsum_and_price(
        regionsum, price, date(2020, 1, 15)
    )

    assert len(rows) == 2
    by_region = {r["region"]: r for r in rows}
    assert by_region["NSW1"]["demand_mw"] == 7245.31
    assert by_region["NSW1"]["price_mwh"] == 49.00916
    assert by_region["QLD1"]["demand_mw"] == 6095.75


def test_parse_mmsdm_regionsum_and_price_filters_to_the_requested_day():
    # A whole real month's CSV covers many days -- only the requested
    # day's rows should survive, since `_fetch_mmsdm_day` is called once
    # per day but the underlying CSVs are cached per month.
    regionsum = _mmsdm_regionsum_csv(
        [
            ("2020/01/15 00:05:00", "NSW1", 7245.31),
            ("2020/01/16 00:05:00", "NSW1", 7300.0),
        ]
    )
    price = _mmsdm_price_csv([("2020/01/15 00:05:00", "NSW1", 49.0)])

    rows = ingest_aemo_nem._parse_mmsdm_regionsum_and_price(
        regionsum, price, date(2020, 1, 15)
    )

    assert len(rows) == 1
    assert rows[0]["demand_mw"] == 7245.31


async def test_fetch_mmsdm_table_csv_caches_within_the_same_month(monkeypatch):
    ingest_aemo_nem._mmsdm_month_cache.clear()
    get_calls = []

    class _FakeMmsdmClient:
        async def get(self, url):
            get_calls.append(url)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("PUBLIC_DVD_DISPATCHREGIONSUM_202001010000.CSV", "C,x\nI,x\n")
            return _FakeResponse(buf.getvalue())

    client = _FakeMmsdmClient()

    await ingest_aemo_nem._fetch_mmsdm_table_csv(client, "DISPATCHREGIONSUM", 2020, 1)
    await ingest_aemo_nem._fetch_mmsdm_table_csv(client, "DISPATCHREGIONSUM", 2020, 1)

    # Second call for the same (table, year, month) hit the cache, not
    # a second real request.
    assert len(get_calls) == 1
    ingest_aemo_nem._mmsdm_month_cache.clear()


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
