"""Tests for ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone

import httpx
import pytest
import respx

from ecolens.ingestion.sources.aemo_nem.client import AEMONEMClient


class TestParseMmsTables:
    """The real PUBLIC_DAILY file is one AEMO MMS multi-table CSV (`I,`
    header rows, `D,` data rows) — NOT the classic per-table-CSV
    NEMWeb format. Also confirmed live: the file bundles two full
    identical copies of DUNIT/DREGION, so this must dedupe."""

    def test_parses_header_and_data_rows_for_wanted_tables(self):
        raw = (
            "C,NEMP.WORLD,DAILY\n"
            "I,DUNIT,,2,SETTLEMENTDATE,DUID,INTERVENTION,TOTALCLEARED\n"
            'D,DUNIT,,2,"2026/07/19 04:05:00",BAYSW1,0,200.5\n'
            "I,DREGION,,2,SETTLEMENTDATE,REGIONID,TOTALDEMAND\n"
            'D,DREGION,,2,"2026/07/19 04:05:00",NSW1,7000\n'
        )
        result = AEMONEMClient._parse_mms_tables(raw, {"DUNIT", "DREGION"})
        assert list(result["DUNIT"].columns) == [
            "SETTLEMENTDATE",
            "DUID",
            "INTERVENTION",
            "TOTALCLEARED",
        ]
        assert result["DUNIT"].iloc[0]["DUID"] == "BAYSW1"
        assert result["DREGION"].iloc[0]["REGIONID"] == "NSW1"

    def test_dedupes_duplicate_rows_bundled_in_real_file(self):
        """Regression: PUBLIC_DAILY bundles two identical copies of
        DUNIT — left undeduped, downstream aggregation would silently
        double-count every generation value."""
        raw = (
            "I,DUNIT,,2,SETTLEMENTDATE,DUID,INTERVENTION,TOTALCLEARED\n"
            'D,DUNIT,,2,"2026/07/19 04:05:00",BAYSW1,0,200.5\n'
            'D,DUNIT,,2,"2026/07/19 04:05:00",BAYSW1,0,200.5\n'  # exact duplicate
        )
        result = AEMONEMClient._parse_mms_tables(raw, {"DUNIT"})
        assert len(result["DUNIT"]) == 1

    def test_ignores_unwanted_tables(self):
        raw = (
            "I,DISPATCH,CASESOLUTION,1,SETTLEMENTDATE\n"
            'D,DISPATCH,CASESOLUTION,1,"2026/07/19 04:05:00"\n'
            "I,DUNIT,,2,SETTLEMENTDATE,DUID\n"
            'D,DUNIT,,2,"2026/07/19 04:05:00",BAYSW1\n'
        )
        result = AEMONEMClient._parse_mms_tables(raw, {"DUNIT"})
        assert "DISPATCH" not in result
        assert len(result["DUNIT"]) == 1

    def test_missing_table_returns_empty_frame(self):
        result = AEMONEMClient._parse_mms_tables("C,NEMP.WORLD\n", {"DUNIT"})
        assert result["DUNIT"].empty


class TestResolveDayUrl:
    @pytest.mark.asyncio
    @respx.mock
    async def test_finds_matching_zip_link_in_directory_listing(self):
        respx.get("https://www.nemweb.com.au/Reports/Current/Daily_Reports/").mock(
            return_value=httpx.Response(
                200,
                text=(
                    '<A HREF="/Reports/CURRENT/Daily_Reports/'
                    'PUBLIC_DAILY_202607190000_20260720040503.zip">x</A>'
                ),
            )
        )
        client = AEMONEMClient()
        async with httpx.AsyncClient() as http:
            url = await client._resolve_day_url(
                http, datetime(2026, 7, 19, tzinfo=timezone.utc)
            )
        assert url == (
            "https://www.nemweb.com.au/Reports/CURRENT/Daily_Reports/"
            "PUBLIC_DAILY_202607190000_20260720040503.zip"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_day_not_published(self):
        respx.get("https://www.nemweb.com.au/Reports/Current/Daily_Reports/").mock(
            return_value=httpx.Response(200, text="<html></html>")
        )
        client = AEMONEMClient()
        async with httpx.AsyncClient() as http:
            url = await client._resolve_day_url(
                http, datetime(2026, 7, 20, tzinfo=timezone.utc)
            )
        assert url is None


class TestFetchDayTables:
    @pytest.mark.asyncio
    @respx.mock
    async def test_full_flow_resolves_downloads_and_parses(self):
        raw_csv = (
            "I,DUNIT,,2,SETTLEMENTDATE,DUID,INTERVENTION,TOTALCLEARED\n"
            'D,DUNIT,,2,"2026/07/19 04:05:00",BAYSW1,0,200.5\n'
            "I,DREGION,,2,SETTLEMENTDATE,REGIONID,TOTALDEMAND\n"
            'D,DREGION,,2,"2026/07/19 04:05:00",NSW1,7000\n'
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("PUBLIC_DAILY_202607190000_20260720040503.CSV", raw_csv)

        respx.get("https://www.nemweb.com.au/Reports/Current/Daily_Reports/").mock(
            return_value=httpx.Response(
                200,
                text=(
                    '<A HREF="/Reports/CURRENT/Daily_Reports/'
                    'PUBLIC_DAILY_202607190000_20260720040503.zip">x</A>'
                ),
            )
        )
        respx.get(
            "https://www.nemweb.com.au/Reports/CURRENT/Daily_Reports/"
            "PUBLIC_DAILY_202607190000_20260720040503.zip"
        ).mock(return_value=httpx.Response(200, content=buf.getvalue()))

        client = AEMONEMClient()
        async with httpx.AsyncClient() as http:
            tables = await client.fetch_day_tables(
                http, datetime(2026, 7, 19, tzinfo=timezone.utc)
            )

        assert tables is not None
        assert tables["DUNIT"].iloc[0]["DUID"] == "BAYSW1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_not_published(self):
        respx.get("https://www.nemweb.com.au/Reports/Current/Daily_Reports/").mock(
            return_value=httpx.Response(200, text="<html></html>")
        )
        client = AEMONEMClient()
        async with httpx.AsyncClient() as http:
            tables = await client.fetch_day_tables(
                http, datetime(2026, 7, 20, tzinfo=timezone.utc)
            )
        assert tables is None


class TestDownloadZipRetry:
    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_transport_errors_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", lambda *_a, **_kw: _noop())

        call_count = {"n": 0}

        def flaky(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise httpx.ConnectTimeout("simulated timeout")
            return httpx.Response(200, content=b"zip-bytes")

        respx.get("https://example.test/file.zip").mock(side_effect=flaky)
        client = AEMONEMClient()
        async with httpx.AsyncClient() as http:
            content = await client._download_zip(http, "https://example.test/file.zip")
        assert content == b"zip-bytes"
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_after_max_retries_exhausted(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", lambda *_a, **_kw: _noop())
        respx.get("https://example.test/file.zip").mock(
            side_effect=httpx.ConnectTimeout("simulated timeout")
        )
        client = AEMONEMClient()
        async with httpx.AsyncClient() as http:
            with pytest.raises(httpx.ConnectTimeout):
                await client._download_zip(http, "https://example.test/file.zip")


async def _noop():
    return None
