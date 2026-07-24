"""Tests for ecolens.warehouse.runner.freshness.SourceFreshnessChecker.

Uses a fake pymongo-shaped client (from conftest.py) so these never
touch a real MongoDB server. Also exercises the actual freshness
comparison logic, which the original script's tests never covered
(they only asserted the "pymongo not installed" skip path, which
never fires in this repo since pymongo is a hard dependency).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import FakeMongoClient, FakeMongoCollection

import ecolens.warehouse.runner.freshness as freshness_module
from ecolens.warehouse.runner.freshness import SourceFreshnessChecker
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings


def _fresh_doc() -> dict:
    return {"fetched_at": datetime.now(timezone.utc) - timedelta(minutes=5)}


def _stale_doc() -> dict:
    return {"fetched_at": datetime.now(timezone.utc) - timedelta(hours=5)}


def _all_fresh_collections() -> dict[str, FakeMongoCollection]:
    return {
        "aemo_nem_dispatch": FakeMongoCollection(doc=_fresh_doc()),
        "aemo_wem_dispatch": FakeMongoCollection(doc=_fresh_doc()),
        "openelectricity_responses": FakeMongoCollection(doc=_fresh_doc()),
        "bom_observations": FakeMongoCollection(doc=_fresh_doc()),
        "aemo_holidays": FakeMongoCollection(doc=_fresh_doc()),
    }


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
        assert "unavailable" in (result.error or "").lower()


class TestConnected:
    def test_all_fresh_sources_succeeds(self, monkeypatch):
        monkeypatch.setattr(
            freshness_module,
            "MongoClient",
            lambda *a, **kw: FakeMongoClient(collections=_all_fresh_collections()),
        )
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        result = checker.check()
        assert result.success is True
        assert result.metrics["all_fresh"] is True
        assert len(result.metrics["sources"]) == 5

    def test_one_stale_source_fails(self, monkeypatch):
        collections = _all_fresh_collections()
        collections["bom_observations"] = FakeMongoCollection(doc=_stale_doc())
        monkeypatch.setattr(
            freshness_module,
            "MongoClient",
            lambda *a, **kw: FakeMongoClient(collections=collections),
        )
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        result = checker.check()
        assert result.success is False
        assert result.error == "one or more sources are stale"
        statuses = {s["collection"]: s["status"] for s in result.metrics["sources"]}
        assert statuses["bom_observations"] == "stale"
        assert statuses["aemo_nem_dispatch"] == "fresh"

    def test_missing_collection_fails(self, monkeypatch):
        collections = _all_fresh_collections()
        collections["aemo_holidays"] = FakeMongoCollection(doc=None)
        monkeypatch.setattr(
            freshness_module,
            "MongoClient",
            lambda *a, **kw: FakeMongoClient(collections=collections),
        )
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        result = checker.check()
        assert result.success is False
        statuses = {s["collection"]: s["status"] for s in result.metrics["sources"]}
        assert statuses["aemo_holidays"] == "missing"

    def test_string_timestamp_is_parsed(self, monkeypatch):
        collections = _all_fresh_collections()
        recent = (
            (datetime.now(timezone.utc) - timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        collections["bom_observations"] = FakeMongoCollection(
            doc={"fetched_at": recent}
        )
        monkeypatch.setattr(
            freshness_module,
            "MongoClient",
            lambda *a, **kw: FakeMongoClient(collections=collections),
        )
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        result = checker.check()
        assert result.success is True

    def test_connect_failure_leaves_client_none(self, monkeypatch):
        monkeypatch.setattr(
            freshness_module,
            "MongoClient",
            lambda *a, **kw: FakeMongoClient(ping_raises=ConnectionError("down")),
        )
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        assert checker._client is None
        result = checker.check(allow_skip=False)
        assert result.success is False

    def test_close_resets_client(self, monkeypatch):
        monkeypatch.setattr(
            freshness_module,
            "MongoClient",
            lambda *a, **kw: FakeMongoClient(collections=_all_fresh_collections()),
        )
        checker = SourceFreshnessChecker(WarehouseRunnerSettings())
        checker.connect()
        assert checker._client is not None
        checker.close()
        assert checker._client is None


class TestSourcesBuiltFromSettings:
    def test_thresholds_come_from_settings_not_hardcoded(self):
        settings = WarehouseRunnerSettings(freshness_threshold_bom=timedelta(minutes=1))
        checker = SourceFreshnessChecker(settings)
        bom_entries = [s for s in checker.sources if s[0] == "bom_observations"]
        assert bom_entries[0][2] == timedelta(minutes=1)
