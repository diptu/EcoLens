"""Tests for ecolens.ingestion.storage.duckdb_store.

Uses a tmp_path-scoped DuckDB file for every test -- never touches the
real historical_duckdb_path -- so these are fast and hermetic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ecolens.ingestion.storage.duckdb_store import read_historical, write_historical


def _doc(station_id: str, ts: datetime, temp_c: float, **overrides) -> dict:
    doc = {
        "station_id": station_id,
        "ts": ts,
        "region": "NSW1",
        "temp_c": temp_c,
        "source": "open_meteo_era5",
    }
    doc.update(overrides)
    return doc


class TestWriteEmpty:
    def test_empty_docs_returns_zero(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        assert write_historical("bom", [], db_path=db_path) == 0

    def test_empty_docs_does_not_create_file(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical("bom", [], db_path=db_path)
        assert not db_path.exists()


class TestWriteThenRead:
    def test_round_trip(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        docs = [
            _doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0),
            _doc("066037", datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc), 21.0),
        ]
        written = write_historical("bom", docs, db_path=db_path)
        assert written == 2

        out = read_historical("bom", db_path=db_path)
        assert len(out) == 2
        assert sorted(out["temp_c"].tolist()) == [20.0, 21.0]

    def test_read_never_written_returns_empty_dataframe(self, tmp_path: Path):
        db_path = tmp_path / "nonexistent.duckdb"
        out = read_historical("bom", db_path=db_path)
        assert out.empty

    def test_read_after_write_of_different_source_returns_empty(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "aemo_nem",
            [
                {
                    "region": "NSW1",
                    "ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "demand_mw": 5000.0,
                }
            ],
            db_path=db_path,
        )
        # File exists (aemo_nem's table was created), but "bom" never was.
        out = read_historical("bom", db_path=db_path)
        assert out.empty


class TestIdempotentUpsert:
    def test_rewriting_same_key_updates_in_place_not_duplicates(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        write_historical("bom", [_doc("066037", ts, 20.0)], db_path=db_path)
        write_historical("bom", [_doc("066037", ts, 99.0)], db_path=db_path)

        out = read_historical("bom", db_path=db_path)
        assert len(out) == 1
        assert out.iloc[0]["temp_c"] == 99.0

    def test_new_key_in_second_batch_is_appended(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0)],
            db_path=db_path,
        )
        write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 2, tzinfo=timezone.utc), 22.0)],
            db_path=db_path,
        )

        out = read_historical("bom", db_path=db_path)
        assert len(out) == 2

    def test_rerunning_identical_batch_is_a_no_op(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        docs = [
            _doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0),
            _doc("066037", datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc), 21.0),
        ]
        write_historical("bom", docs, db_path=db_path)
        write_historical("bom", docs, db_path=db_path)

        out = read_historical("bom", db_path=db_path)
        assert len(out) == 2


class TestUnknownSource:
    def test_write_unknown_source_raises_keyerror(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        with pytest.raises(KeyError, match="Unknown source"):
            write_historical("not_a_real_source", [{"a": 1}], db_path=db_path)
