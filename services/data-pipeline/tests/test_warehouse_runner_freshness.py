"""Tests for ecolens.warehouse.service.freshness.SourceFreshnessChecker.

Checks DuckDB (via `duckdb_store.latest_fetched_at`, monkeypatched here)
rather than a live database -- `connect()` only needs a real file to
exist at `Settings.historical_duckdb_path` for `_db_path` to get set;
the per-source freshness comparison itself never touches the file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import ecolens.warehouse.service.freshness as freshness_module
from ecolens.warehouse.service.freshness import SourceFreshnessChecker
from ecolens.warehouse.core.runner_settings import WarehouseRunnerSettings

ALL_SOURCES = ["aemo_nem", "aemo_wem", "openelectricity", "bom", "aemo_holidays"]


def _fresh_ts() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=5)


def _stale_ts() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=5)


def _connect(checker: SourceFreshnessChecker, tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "ecolens_historical.duckdb"
    db_path.touch()
    monkeypatch.setattr(
        freshness_module,
        "get_settings",
        lambda: SimpleNamespace(historical_duckdb_path=db_path),
    )
    checker.connect()


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


class TestConnected:
    def test_all_fresh_sources_succeeds(self, tmp_path, monkeypatch):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        _connect(checker, tmp_path, monkeypatch)
        monkeypatch.setattr(
            freshness_module.duckdb_store,
            "latest_fetched_at",
            lambda source, **kw: _fresh_ts(),
        )
        result = checker.check()
        assert result.success is True
        assert result.metrics["all_fresh"] is True
        assert len(result.metrics["sources"]) == len(ALL_SOURCES)

    def test_one_stale_source_fails(self, tmp_path, monkeypatch):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        _connect(checker, tmp_path, monkeypatch)

        def fake_latest(source, **kw):
            return _stale_ts() if source == "bom" else _fresh_ts()

        monkeypatch.setattr(
            freshness_module.duckdb_store, "latest_fetched_at", fake_latest
        )
        result = checker.check()
        assert result.success is False
        assert result.error == "one or more sources are stale"
        statuses = {s["source"]: s["status"] for s in result.metrics["sources"]}
        assert statuses["bom"] == "stale"
        assert statuses["aemo_nem"] == "fresh"

    def test_missing_source_fails(self, tmp_path, monkeypatch):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        _connect(checker, tmp_path, monkeypatch)

        def fake_latest(source, **kw):
            return None if source == "aemo_holidays" else _fresh_ts()

        monkeypatch.setattr(
            freshness_module.duckdb_store, "latest_fetched_at", fake_latest
        )
        result = checker.check()
        assert result.success is False
        statuses = {s["source"]: s["status"] for s in result.metrics["sources"]}
        assert statuses["aemo_holidays"] == "missing"

    def test_naive_timestamp_is_treated_as_utc(self, tmp_path, monkeypatch):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        _connect(checker, tmp_path, monkeypatch)
        naive_recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            minutes=1
        )
        monkeypatch.setattr(
            freshness_module.duckdb_store,
            "latest_fetched_at",
            lambda source, **kw: naive_recent,
        )
        result = checker.check()
        assert result.success is True

    def test_check_failure_returns_failed_stage(self, tmp_path, monkeypatch):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        _connect(checker, tmp_path, monkeypatch)

        def raises(source, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(freshness_module.duckdb_store, "latest_fetched_at", raises)
        result = checker.check(allow_skip=False)
        assert result.success is False
        assert "boom" in (result.error or "")

    def test_close_resets_db_path(self, tmp_path, monkeypatch):
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        _connect(checker, tmp_path, monkeypatch)
        assert checker._db_path is not None
        checker.close()
        assert checker._db_path is None


class TestSourcesBuiltFromSettings:
    def test_thresholds_come_from_settings_not_hardcoded(self):
        settings = WarehouseRunnerSettings(freshness_threshold_bom=timedelta(minutes=1))
        checker = SourceFreshnessChecker(settings)
        bom_entries = [s for s in checker.sources if s[0] == "bom"]
        assert bom_entries[0][1] == timedelta(minutes=1)
