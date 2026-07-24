"""Tests for ecolens.ingestion.sources.bom.cache (read_cache/write_cache)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ecolens.ingestion.sources.bom.cache import read_cache, write_cache


def _doc(**overrides) -> dict:
    base = {
        "ts": pd.Timestamp("2024-01-01T06:00:00Z"),
        "region": "NSW1",
        "station_id": "066037",
        "station_name": "Sydney",
        "schema_version": "1.0",
        "temp_c": 22.0,
        "source": "bom",
    }
    base.update(overrides)
    return base


class TestWriteThenRead:
    def test_write_then_read_round_trips(self, tmp_path):
        docs = [_doc()]
        paths = write_cache(tmp_path, docs, region="NSW1")
        assert len(paths) == 1
        assert paths[0].exists()

        since = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        until = datetime(2024, 1, 1, 23, 59, tzinfo=timezone.utc)
        cached = read_cache(tmp_path, since, until)
        nsw = [d for d in cached if d["region"] == "NSW1"]
        assert len(nsw) == 1
        assert nsw[0]["station_id"] == "066037"

    def test_dedup_on_append(self, tmp_path):
        doc = _doc()
        write_cache(tmp_path, [doc], region="NSW1")
        write_cache(tmp_path, [doc], region="NSW1")
        files = list(tmp_path.glob("observations_NSW1_*.csv"))
        assert len(files) == 1
        df = pd.read_csv(files[0])
        assert len(df) == 1

    def test_no_cache_dir_returns_empty(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        until = datetime(2024, 1, 2, tzinfo=timezone.utc)
        assert read_cache(missing, since, until) == []

    def test_empty_docs_writes_nothing(self, tmp_path):
        assert write_cache(tmp_path, []) == []

    def test_region_filter_skips_other_regions(self, tmp_path):
        docs = [_doc(region="NSW1"), _doc(region="VIC1", station_id="086282")]
        paths = write_cache(tmp_path, docs, region="NSW1")
        assert len(paths) == 1
        assert "NSW1" in paths[0].name
