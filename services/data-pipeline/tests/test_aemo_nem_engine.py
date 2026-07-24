"""Tests for ecolens.ingestion.sources.aemo_nem.engine.AEMONEMFetcher."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pandas as pd
import pytest

from ecolens.ingestion.sources.aemo_nem.engine import AEMONEMFetcher
from ecolens.ingestion.sources.aemo_nem.schema import OUTPUT_COLUMNS


def _fake_tables() -> dict[str, pd.DataFrame]:
    return {
        "DUNIT": pd.DataFrame(
            [
                {
                    "SETTLEMENTDATE": "2026/07/19 04:05:00",
                    "DUID": "BAYSW1",
                    "INTERVENTION": "0",
                    "TOTALCLEARED": "200.0",
                }
            ]
        ),
        "DREGION": pd.DataFrame(
            [
                {
                    "SETTLEMENTDATE": "2026/07/19 04:05:00",
                    "INTERVENTION": "0",
                    "REGIONID": "NSW1",
                    "TOTALDEMAND": "7000.0",
                    "RRP": "85.5",
                    "NETINTERCHANGE": "0.0",
                }
            ]
        ),
    }


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_builds_full_output_schema(self, monkeypatch):
        fetcher = AEMONEMFetcher(duid_fueltech_map={"BAYSW1": "coal_black"})

        async def fake_fetch_day_tables(self, client, day):
            return _fake_tables()

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
                until=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
            )

        assert len(docs) == 2  # one NEM row, one NSW1 row
        assert all(set(doc.keys()) == set(OUTPUT_COLUMNS) for doc in docs)
        nem_doc = next(d for d in docs if d["region"] == "NEM")
        assert nem_doc["coal_black_mw"] == 200.0

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_list_when_day_not_published(self, monkeypatch):
        fetcher = AEMONEMFetcher()

        async def fake_fetch_day_tables(self, client, day):
            return None

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
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
        fetcher = AEMONEMFetcher(duid_fueltech_map={"BAYSW1": "coal_black"})

        async def flaky_fetch_day_tables(self, client, day):
            if day.day == 19:
                raise RuntimeError("network boom")
            return _fake_tables()

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            flaky_fetch_day_tables,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
                until=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
            )
        # Day 19 failed, day 20 succeeded -> still get day 20's rows.
        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_defaults_since_and_until_when_omitted(self, monkeypatch):
        fetcher = AEMONEMFetcher()
        seen_days = []

        async def fake_fetch_day_tables(self, client, day):
            seen_days.append(day.date())
            return None

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client
            )  # no since/until -> defaults to "last hour"
        assert docs == []
        assert len(seen_days) >= 1

    @pytest.mark.asyncio
    async def test_http_404_treated_as_day_not_published(self, monkeypatch):
        fetcher = AEMONEMFetcher()

        async def fake_fetch_day_tables(self, client, day):
            raise httpx.HTTPStatusError(
                "not found",
                request=httpx.Request("GET", "https://x"),
                response=httpx.Response(404, request=httpx.Request("GET", "https://x")),
            )

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, tzinfo=timezone.utc),
                until=datetime(2026, 7, 19, tzinfo=timezone.utc),
            )
        assert docs == []

    @pytest.mark.asyncio
    async def test_http_500_logs_error_and_continues(self, monkeypatch):
        fetcher = AEMONEMFetcher()

        async def fake_fetch_day_tables(self, client, day):
            raise httpx.HTTPStatusError(
                "server error",
                request=httpx.Request("GET", "https://x"),
                response=httpx.Response(500, request=httpx.Request("GET", "https://x")),
            )

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, tzinfo=timezone.utc),
                until=datetime(2026, 7, 19, tzinfo=timezone.utc),
            )
        assert docs == []

    @pytest.mark.asyncio
    async def test_until_before_since_raises(self):
        fetcher = AEMONEMFetcher()
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError):
                await fetcher.fetch(
                    client,
                    since=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    until=datetime(2026, 7, 19, tzinfo=timezone.utc),
                )

    @pytest.mark.asyncio
    async def test_aggregate_to_network_rolls_up_regions(self, monkeypatch):
        fetcher = AEMONEMFetcher(
            aggregate_to_network=True, duid_fueltech_map={"BAYSW1": "coal_black"}
        )

        async def fake_fetch_day_tables(self, client, day):
            return _fake_tables()

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
        )
        async with httpx.AsyncClient() as client:
            docs = await fetcher.fetch(
                client,
                since=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
                until=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
            )
        assert all(d["region"] == "NEM" for d in docs)


class TestFetchForDate:
    @pytest.mark.asyncio
    async def test_explicit_date_is_used(self, monkeypatch):
        fetcher = AEMONEMFetcher(duid_fueltech_map={"BAYSW1": "coal_black"})
        seen_days = []

        async def fake_fetch_day_tables(self, client, day):
            seen_days.append(day.date())
            return _fake_tables()

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
        )
        async with httpx.AsyncClient() as client:
            await fetcher.fetch_for_date(client, date(2026, 7, 15))
        assert seen_days == [date(2026, 7, 15)]

    @pytest.mark.asyncio
    async def test_defaults_to_yesterday_aest(self, monkeypatch):
        fetcher = AEMONEMFetcher()
        seen_days = []

        async def fake_fetch_day_tables(self, client, day):
            seen_days.append(day.date())
            return None

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.client.AEMONEMClient.fetch_day_tables",
            fake_fetch_day_tables,
        )

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(
                    2026, 7, 21, 1, 0, tzinfo=timezone.utc
                )  # ~11am AEST on the 21st

        monkeypatch.setattr(
            "ecolens.ingestion.sources.aemo_nem.engine.datetime", FixedDatetime
        )
        async with httpx.AsyncClient() as client:
            await fetcher.fetch_for_date(client)
        assert seen_days == [date(2026, 7, 20)]


class TestDaterange:
    def test_single_day_range(self):
        days = AEMONEMFetcher._daterange(
            datetime(2026, 7, 19, 5), datetime(2026, 7, 19, 23)
        )
        assert days == [datetime(2026, 7, 19)]

    def test_multi_day_range_inclusive(self):
        days = AEMONEMFetcher._daterange(datetime(2026, 7, 19), datetime(2026, 7, 21))
        assert days == [
            datetime(2026, 7, 19),
            datetime(2026, 7, 20),
            datetime(2026, 7, 21),
        ]
