"""Tests for ecolens.warehouse.runner.freshness.SourceFreshnessChecker.

Uses a real tmp_path-scoped DuckDB file (written via
ecolens.ingestion.storage.duckdb_store.write_historical) rather than a
mock -- freshness's whole job is "read what's actually in the store", so
exercising the real read path is more direct than reimplementing it with
a double. To simulate a *stale* source, a row is written (which always
stamps `fetched_at` to "now") and then directly backdated with a raw
UPDATE -- write_historical itself has no way to accept a caller-supplied
fetched_at, by design (it should always reflect the real write time).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import duckdb
import pytest

from ecolens.config import get_settings
from ecolens.ingestion.storage import duckdb_store
from ecolens.ingestion.storage.duckdb_store import write_historical
from ecolens.warehouse.runner.freshness import SourceFreshnessChecker
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings

_ALL_SOURCES = ["aemo_nem", "aemo_wem", "openelectricity", "bom", "aemo_holidays"]


@pytest.fixture(autouse=True)
def _duckdb_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HISTORICAL_DUCKDB_PATH", str(tmp_path / "historical.duckdb"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _doc(source: str) -> dict:
    if source == "bom":
        return {"station_id": "1", "ts": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    if source == "aemo_wem":
        return {"ts": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    if source == "aemo_holidays":
        return {"region": "NSW1", "date": "2026-01-01"}
    if source == "openelectricity":
        return {"network_code": "NEM", "ts": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    return {"region": "NSW1", "ts": datetime(2026, 1, 1, tzinfo=timezone.utc)}


def _write_all_fresh() -> None:
    for source in _ALL_SOURCES:
        write_historical(source, [_doc(source)])


def _backdate(source: str, age: timedelta) -> None:
    """Directly rewrite a source's fetched_at to simulate staleness."""
    path = get_settings().historical_duckdb_path.resolve()
    table = duckdb_store.get_ingestion_settings().table_for_source(source)
    con = duckdb.connect(str(path))
    try:
        con.execute(
            f'UPDATE "{table}" SET fetched_at = ?', [datetime.now(timezone.utc) - age]
        )
    finally:
        con.close()


class TestNotConnected:
    def test_allow_skip_true_returns_success(self):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        result = checker.check(allow_skip=True)
        assert result.success is True
        assert result.metrics.get("status") == "skipped"
        assert result.error is None

    def test_allow_skip_false_returns_failure(self):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        result = checker.check(allow_skip=False)
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    def test_connect_with_no_store_leaves_db_path_none(self):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        assert checker._db_path is None


class TestConnected:
    def test_all_fresh_sources_succeeds(self):
        _write_all_fresh()
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        result = checker.check()
        assert result.success is True
        assert result.metrics["all_fresh"] is True
        assert len(result.metrics["sources"]) == 5

    def test_one_stale_source_fails(self):
        _write_all_fresh()
        _backdate("bom", timedelta(hours=5))  # exceeds freshness_threshold_bom (2h)
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        result = checker.check()
        assert result.success is False
        assert result.error == "one or more sources are stale"
        statuses = {s["source"]: s["status"] for s in result.metrics["sources"]}
        assert statuses["bom"] == "stale"
        assert statuses["aemo_nem"] == "fresh"

    def test_missing_source_fails(self):
        for source in _ALL_SOURCES:
            if source != "aemo_holidays":
                write_historical(source, [_doc(source)])
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        result = checker.check()
        assert result.success is False
        statuses = {s["source"]: s["status"] for s in result.metrics["sources"]}
        assert statuses["aemo_holidays"] == "missing"

    def test_check_failure_returns_failed_stage(self, monkeypatch):
        _write_all_fresh()
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(duckdb_store, "latest_fetched_at", _boom)
        result = checker.check()
        assert result.success is False
        assert "boom" in (result.error or "")

    def test_close_resets_db_path(self):
        _write_all_fresh()
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        assert checker._db_path is not None
        checker.close()
        assert checker._db_path is None


class TestSourcesBuiltFromSettings:
    def test_thresholds_come_from_settings_not_hardcoded(self):
        settings = WarehouseRunnerSettings(freshness_threshold_bom=timedelta(minutes=1))
        checker = SourceFreshnessChecker(settings)
        bom_entries = [s for s in checker.sources if s[0] == "bom"]
        assert bom_entries[0][1] == timedelta(minutes=1)
