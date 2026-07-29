"""Tests for scripts/migrate_add_anomaly_columns.py."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migrate_add_anomaly_columns import _NEW_COLUMNS, migrate


def _legacy_table(db_path: Path, table: str) -> None:
    con = duckdb.connect(str(db_path))
    con.execute(f"CREATE TABLE {table} (ts TIMESTAMPTZ, region TEXT, demand_mw DOUBLE)")
    con.close()


class TestMigrate:
    def test_adds_columns_to_an_existing_table(self, tmp_path: Path):
        db_path = tmp_path / "legacy.duckdb"
        _legacy_table(db_path, "aemo_nem_dispatch")

        migrated = migrate(db_path)
        assert migrated == ["aemo_nem_dispatch"]

        con = duckdb.connect(str(db_path), read_only=True)
        columns = {
            row[0] for row in con.execute("DESCRIBE aemo_nem_dispatch").fetchall()
        }
        con.close()
        for column, _ in _NEW_COLUMNS:
            assert column in columns

    def test_idempotent_safe_to_run_twice(self, tmp_path: Path):
        db_path = tmp_path / "legacy.duckdb"
        _legacy_table(db_path, "aemo_nem_dispatch")

        migrate(db_path)
        migrate(db_path)  # must not raise

        con = duckdb.connect(str(db_path), read_only=True)
        columns = [
            row[0] for row in con.execute("DESCRIBE aemo_nem_dispatch").fetchall()
        ]
        con.close()
        # No duplicate columns from running twice.
        assert columns.count("anomaly_score") == 1

    def test_skips_tables_that_do_not_exist(self, tmp_path: Path):
        db_path = tmp_path / "empty.duckdb"
        con = duckdb.connect(str(db_path))
        con.close()

        migrated = migrate(db_path)
        assert migrated == []

    def test_only_migrates_tables_that_exist(self, tmp_path: Path):
        db_path = tmp_path / "partial.duckdb"
        _legacy_table(db_path, "aemo_nem_dispatch")
        _legacy_table(db_path, "bom_observations")

        migrated = migrate(db_path)
        assert set(migrated) == {"aemo_nem_dispatch", "bom_observations"}

    def test_preserves_existing_data(self, tmp_path: Path):
        db_path = tmp_path / "legacy.duckdb"
        con = duckdb.connect(str(db_path))
        con.execute(
            "CREATE TABLE aemo_nem_dispatch (ts TIMESTAMPTZ, region TEXT, demand_mw DOUBLE)"
        )
        con.execute(
            "INSERT INTO aemo_nem_dispatch VALUES ('2026-01-01 00:00:00+00', 'NSW1', 6000.0)"
        )
        con.close()

        migrate(db_path)

        con = duckdb.connect(str(db_path), read_only=True)
        row = con.execute("SELECT region, demand_mw FROM aemo_nem_dispatch").fetchone()
        con.close()
        assert row == ("NSW1", 6000.0)
