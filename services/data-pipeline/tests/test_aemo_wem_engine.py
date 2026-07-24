"""Tests for ecolens.ingestion.sources.aemo_wem.engine.AEMOWEMFetcher."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest

from ecolens.ingestion.sources.aemo_wem.engine import AEMOWEMFetcher
from ecolens.ingestion.sources.aemo_wem.schema import OUTPUT_COLUMNS


def _fake_raw() -> dict:
    return {
        "scada": [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "code": "BW1_BLUEWATERS_G2",
                "quantity": 17.94,
            }
        ],
        "demand": [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "operationalDemand": 2326.5,
            }
        ],
        "price": [
            {
                "tradingInterval": "2026-07-19T08:00:00+08:00",
                "referenceTradingPrice": 137.64,
            }
        ],
    }


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_builds_full_output_schema(self, monkeypatch):
        fetcher = AEMOWEMFetcher(
            facility_fueltech_map={"BW1_BLUEWATERS_G2": "coal_black"}
        )

        async def fake_fetch_day_data(self, client, day):
            return _fake_raw()

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient.fetch_day_data",
            fake_fetch_day_data,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
                until=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
            )

        assert len(docs) == 1
        assert set(docs[0].keys()) == set(OUTPUT_COLUMNS)
        assert docs[0]["region"] == "WEM"
        assert docs[0]["coal_black_mw"] == pytest.approx(17.94 * 12)
        assert docs[0]["demand_mw"] == 2326.5

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_list_when_day_not_published(self, monkeypatch):
        fetcher = AEMOWEMFetcher()

        async def fake_fetch_day_data(self, client, day):
            return None

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient.fetch_day_data",
            fake_fetch_day_data,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
                until=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
            )
        assert docs == []

    @pytest.mark.asyncio
    async def test_fetch_survives_a_failing_day_and_continues_others(self, monkeypatch):
        fetcher = AEMOWEMFetcher(
            facility_fueltech_map={"BW1_BLUEWATERS_G2": "coal_black"}
        )

        async def flaky_fetch_day_data(self, client, day):
            if day.day == 19:
                raise RuntimeError("network boom")
            return _fake_raw()

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient.fetch_day_data",
            flaky_fetch_day_data,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
                until=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
            )
        assert len(docs) == 1  # only day 20 succeeded

    @pytest.mark.asyncio
    async def test_defaults_since_and_until_when_omitted(self, monkeypatch):
        fetcher = AEMOWEMFetcher()
        seen_days = []

        async def fake_fetch_day_data(self, client, day):
            seen_days.append(day)
            return None

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient.fetch_day_data",
            fake_fetch_day_data,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(client)
        assert docs == []
        assert len(seen_days) >= 1

    @pytest.mark.asyncio
    async def test_until_before_since_raises(self):
        fetcher = AEMOWEMFetcher()
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError):
                await fetcher.fetch(
                    client,
                    since=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    until=datetime(2026, 7, 19, tzinfo=timezone.utc),
                )

    @pytest.mark.asyncio
    async def test_generic_exception_logged_and_day_skipped(self, monkeypatch):
        fetcher = AEMOWEMFetcher()

        async def flaky_fetch_day_data(self, client, day):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient.fetch_day_data",
            flaky_fetch_day_data,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, tzinfo=timezone.utc),
                until=datetime(2026, 7, 19, tzinfo=timezone.utc),
            )
        assert docs == []


class TestFetchForDate:
    @pytest.mark.asyncio
    async def test_explicit_date_is_used(self, monkeypatch):
        fetcher = AEMOWEMFetcher(
            facility_fueltech_map={"BW1_BLUEWATERS_G2": "coal_black"}
        )
        seen_days = []

        async def fake_fetch_day_data(self, client, day):
            seen_days.append(day)
            return _fake_raw()

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient.fetch_day_data",
            fake_fetch_day_data,
        )
        async with httpx.AsyncClient() as client:
            await fetcher.fetch_for_date(client, date(2026, 7, 15))
        assert seen_days == [date(2026, 7, 15)]

    @pytest.mark.asyncio
    async def test_defaults_to_yesterday_awst(self, monkeypatch):
        fetcher = AEMOWEMFetcher()
        seen_days = []

        async def fake_fetch_day_data(self, client, day):
            seen_days.append(day)
            return None

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.client.AEMOWEMClient.fetch_day_data",
            fake_fetch_day_data,
        )

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(
                    2026, 7, 21, 1, 0, tzinfo=timezone.utc
                )  # ~9am AWST on the 21st

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_wem.engine.datetime", FixedDatetime
        )
        async with httpx.AsyncClient() as client:
            await fetcher.fetch_for_date(client)
        assert seen_days == [date(2026, 7, 20)]


class TestDaterange:
    def test_single_day_range(self):
        days = AEMOWEMFetcher._daterange(
            datetime(2026, 7, 19, 5), datetime(2026, 7, 19, 23)
        )
        assert days == [datetime(2026, 7, 19)]

    def test_multi_day_range_inclusive(self):
        days = AEMOWEMFetcher._daterange(datetime(2026, 7, 19), datetime(2026, 7, 21))
        assert days == [
            datetime(2026, 7, 19),
            datetime(2026, 7, 20),
            datetime(2026, 7, 21),
        ]
