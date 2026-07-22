"""Tests for ecolens.ingestion.sources.bom.historical.HistoricalFetcher."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from ecolens.ingestion.sources.bom.historical import HistoricalFetcher

STATIONS = {"NSW1": "066037", "VIC1": "086282"}


class TestConstruction:
    def test_cache_dir_created_on_init(self, tmp_path):
        new_dir = tmp_path / "deeply" / "nested" / "cache"
        HistoricalFetcher(cache_dir=new_dir)
        assert new_dir.exists()

    def test_custom_stations_override_default(self, tmp_path):
        fetcher = HistoricalFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
        assert fetcher.stations == STATIONS

    def test_default_construction_uses_settings_stations(self, tmp_path):
        fetcher = HistoricalFetcher(cache_dir=tmp_path)
        assert len(fetcher.stations) == 6


class TestChunkRange:
    def test_short_range_is_a_single_chunk(self, tmp_path):
        fetcher = HistoricalFetcher(cache_dir=tmp_path)
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)
        chunks = fetcher._chunk_range(start, end)
        assert chunks == [(start, end)]

    def test_splits_at_365_days(self, tmp_path):
        fetcher = HistoricalFetcher(cache_dir=tmp_path)
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=365 * 3)
        chunks = fetcher._chunk_range(start, end)
        assert len(chunks) == 3
        assert chunks[0][0] == start
        # Chunks are contiguous, no gaps or overlaps
        for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
            assert next_start == prev_end + timedelta(days=1)
        assert chunks[-1][1] == end


class TestFetchRange:
    @pytest.mark.asyncio
    async def test_aggregates_across_chunks(self, tmp_path, monkeypatch):
        fetcher = HistoricalFetcher(cache_dir=tmp_path)
        calls = []

        async def fake_fetch_chunk(client, region, start, end, stations):
            calls.append((region, start, end))
            return [{"region": region, "ts": start}]

        monkeypatch.setattr(fetcher._client, "fetch_chunk", fake_fetch_chunk)
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=365 * 2)  # -> 2 chunks
        docs = await fetcher.fetch_range(httpx.AsyncClient(), "NSW1", start, end)
        assert len(docs) == 2
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_returns_none_if_any_chunk_fails(self, tmp_path, monkeypatch):
        fetcher = HistoricalFetcher(cache_dir=tmp_path)
        call_count = 0

        async def flaky_fetch_chunk(client, region, start, end, stations):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return None
            return [{"region": region, "ts": start}]

        monkeypatch.setattr(fetcher._client, "fetch_chunk", flaky_fetch_chunk)
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=365 * 3)  # -> 3 chunks
        docs = await fetcher.fetch_range(httpx.AsyncClient(), "NSW1", start, end)
        assert docs is None


class TestFetchAllStations:
    @pytest.mark.asyncio
    async def test_aggregates_across_regions(self, tmp_path, monkeypatch):
        fetcher = HistoricalFetcher(bom_stations=STATIONS, cache_dir=tmp_path)

        async def fake_fetch_range(client, region, start, end):
            return [{"region": region, "ts": start}]

        monkeypatch.setattr(fetcher, "fetch_range", fake_fetch_range)
        docs = await fetcher.fetch_all_stations(httpx.AsyncClient(), years=1)
        assert {d["region"] for d in docs} == {"NSW1", "VIC1"}

    @pytest.mark.asyncio
    async def test_continues_when_one_region_fails(self, tmp_path, monkeypatch):
        fetcher = HistoricalFetcher(bom_stations=STATIONS, cache_dir=tmp_path)

        async def fake_fetch_range(client, region, start, end):
            if region == "VIC1":
                return None
            return [{"region": region, "ts": start}]

        monkeypatch.setattr(fetcher, "fetch_range", fake_fetch_range)
        docs = await fetcher.fetch_all_stations(httpx.AsyncClient(), years=1)
        assert {d["region"] for d in docs} == {"NSW1"}

    @pytest.mark.asyncio
    async def test_end_date_respects_era5_lag(self, tmp_path, monkeypatch):
        fetcher = HistoricalFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
        seen_ranges = []

        async def fake_fetch_range(client, region, start, end):
            seen_ranges.append((start, end))
            return []

        monkeypatch.setattr(fetcher, "fetch_range", fake_fetch_range)
        await fetcher.fetch_all_stations(httpx.AsyncClient(), years=1)
        now = datetime.now(timezone.utc)
        for _start, end in seen_ranges:
            age = now - end
            assert age >= timedelta(days=5)


class TestFetchAllStationsForRange:
    @pytest.mark.asyncio
    async def test_aggregates_across_regions_for_explicit_range(
        self, tmp_path, monkeypatch
    ):
        fetcher = HistoricalFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
        seen_ranges = []

        async def fake_fetch_range(client, region, start, end):
            seen_ranges.append((region, start, end))
            return [{"region": region, "ts": start}]

        monkeypatch.setattr(fetcher, "fetch_range", fake_fetch_range)
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        end = datetime(2023, 12, 31, tzinfo=timezone.utc)
        docs = await fetcher.fetch_all_stations_for_range(
            httpx.AsyncClient(), start, end
        )
        assert {d["region"] for d in docs} == {"NSW1", "VIC1"}
        assert all(s == start and e == end for _r, s, e in seen_ranges)

    @pytest.mark.asyncio
    async def test_end_before_start_raises(self, tmp_path):
        fetcher = HistoricalFetcher(cache_dir=tmp_path)
        start = datetime(2023, 6, 1, tzinfo=timezone.utc)
        end = datetime(2023, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            await fetcher.fetch_all_stations_for_range(httpx.AsyncClient(), start, end)

    @pytest.mark.asyncio
    async def test_fetch_all_stations_delegates_to_for_range(
        self, tmp_path, monkeypatch
    ):
        fetcher = HistoricalFetcher(bom_stations=STATIONS, cache_dir=tmp_path)
        seen: list[tuple] = []

        async def fake_for_range(client, start, end):
            seen.append((start, end))
            return []

        monkeypatch.setattr(fetcher, "fetch_all_stations_for_range", fake_for_range)
        await fetcher.fetch_all_stations(httpx.AsyncClient(), years=2)
        assert len(seen) == 1
        start, end = seen[0]
        assert (end - start).days == pytest.approx(365 * 2, abs=1)


class TestWriteCache:
    def test_delegates_to_cache_module(self, tmp_path, monkeypatch):
        fetcher = HistoricalFetcher(cache_dir=tmp_path)
        calls = []

        def fake_write_cache(cache_dir, docs):
            calls.append((cache_dir, docs))
            return []

        import ecolens.ingestion.sources.bom.historical as historical_module

        monkeypatch.setattr(
            historical_module.cache_module, "write_cache", fake_write_cache
        )
        docs = [{"region": "NSW1"}]
        fetcher.write_cache(docs)
        assert calls == [(tmp_path, docs)]
