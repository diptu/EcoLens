"""End-to-end (mocked HTTP) tests for ecolens.ingestion.sources.holidays.engine.HolidayFetcher."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from ecolens.ingestion.sources.holidays.engine import HolidayFetcher

DATASTORE_URL_REGEX = r"https://data\.gov\.au/data/api/3/action/datastore_search.*"


class TestConstruction:
    def test_default_uses_six_regions(self, tmp_path):
        f = HolidayFetcher(cache_dir=tmp_path)
        assert len(f.regions) == 6

    def test_custom_regions(self, tmp_path):
        f = HolidayFetcher(cache_dir=tmp_path, regions=("NSW1", "VIC1"))
        assert f.regions == ("NSW1", "VIC1")

    def test_injectable_today(self, tmp_path):
        fixed = date(2026, 1, 1)
        f = HolidayFetcher(cache_dir=tmp_path, today=fixed)
        assert f._today == fixed

    def test_cache_dir_created_on_init(self, tmp_path):
        new_dir = tmp_path / "deeply" / "nested" / "cache"
        HolidayFetcher(cache_dir=new_dir)
        assert new_dir.exists()


class TestFetchForYear:
    def test_sync_fetch_uses_synthetic_when_no_cache(self, tmp_path):
        f = HolidayFetcher(cache_dir=tmp_path)
        docs = f.fetch_for_year(2026)
        assert len(docs) > 0
        assert docs[0]["days_until"] is not None

    def test_sync_fetch_uses_cache_when_available(self, tmp_path):
        f = HolidayFetcher(cache_dir=tmp_path)
        stub_docs = f.fetch_for_year(2026)
        f.write_cache(stub_docs, year=2026)

        f2 = HolidayFetcher(cache_dir=tmp_path)
        cached_docs = f2.fetch_for_year(2026)
        assert {d["source"] for d in cached_docs} == {"synthetic"}


class TestFetch:
    @pytest.mark.asyncio
    @respx.mock
    async def test_uses_live_api_when_available(self, tmp_path):
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
                            }
                        ]
                    }
                },
            )
        )
        f = HolidayFetcher(cache_dir=tmp_path, regions=("NSW1",))
        async with httpx.AsyncClient() as client:
            docs = await f.fetch(client, year=2026)

        assert len(docs) == 1
        assert docs[0]["source"] == "data_gov_au"
        assert docs[0]["region"] == "NSW1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_cache_when_live_api_down(self, tmp_path, monkeypatch):
        async def no_sleep(*_args, **_kwargs):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        f = HolidayFetcher(cache_dir=tmp_path, regions=("NSW1",))
        stub_docs = f.fetch_for_year(2026)
        f.write_cache(stub_docs, year=2026)

        respx.get(url__regex=DATASTORE_URL_REGEX).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            docs = await f.fetch(client, year=2026)

        assert len(docs) > 0
        assert {d["source"] for d in docs} == {"synthetic"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_synthetic_when_nothing_else_available(
        self, tmp_path, monkeypatch
    ):
        async def no_sleep(*_args, **_kwargs):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        respx.get(url__regex=DATASTORE_URL_REGEX).mock(return_value=httpx.Response(500))
        f = HolidayFetcher(cache_dir=tmp_path)
        async with httpx.AsyncClient() as client:
            docs = await f.fetch(client, year=2026)

        assert len(docs) > 0
        assert {d["source"] for d in docs} == {"synthetic"}

    @pytest.mark.asyncio
    async def test_no_client_skips_live_tier(self, tmp_path):
        f = HolidayFetcher(cache_dir=tmp_path)
        docs = await f.fetch(None, year=2026)
        assert len(docs) > 0
