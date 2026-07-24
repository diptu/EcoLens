"""Tests for ecolens.ingestion.sources.holidays.cache (read_cache/write_cache)."""

from __future__ import annotations

from datetime import datetime, timezone

from ecolens.ingestion.sources.holidays.cache import read_cache, write_cache
from ecolens.ingestion.sources.holidays.schema import NEM_REGIONS


def _doc(**overrides) -> dict:
    base = {
        "date": "2026-01-01",
        "region": "NSW1",
        "state": "NSW",
        "holiday_name": "New Year's Day",
        "holiday_type": "national",
        "schema_version": "1.0",
        "source": "synthetic",
        "fetched_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


class TestWriteThenRead:
    def test_write_then_read_round_trips(self, tmp_path):
        docs = [_doc()]
        paths = write_cache(tmp_path, docs, year=2026)
        assert len(paths) == 1
        assert paths[0].exists()

        cached = read_cache(tmp_path, NEM_REGIONS, 2026)
        nsw = [d for d in cached if d["region"] == "NSW1"]
        assert len(nsw) == 1

    def test_dedup_on_append(self, tmp_path):
        doc = _doc()
        write_cache(tmp_path, [doc], year=2026)
        write_cache(tmp_path, [doc], year=2026)
        files = list(tmp_path.glob("holidays_NSW1_*.csv"))
        assert len(files) == 1
        cached = read_cache(tmp_path, ("NSW1",), 2026)
        assert len(cached) == 1

    def test_no_cache_dir_returns_empty(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        assert read_cache(missing, NEM_REGIONS, 2026) == []

    def test_empty_docs_writes_nothing(self, tmp_path):
        assert write_cache(tmp_path, [], year=2026) == []

    def test_one_file_per_region(self, tmp_path):
        docs = [_doc(region="NSW1"), _doc(region="VIC1", state="VIC")]
        paths = write_cache(tmp_path, docs, year=2026)
        assert len(paths) == 2
        names = {p.name for p in paths}
        assert "holidays_NSW1_2026.csv" in names
        assert "holidays_VIC1_2026.csv" in names
