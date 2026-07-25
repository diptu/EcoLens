"""Tests for ecolens.warehouse.runner.archive.ArchiveManager.

Uses a fake psycopg2-shaped double (conftest.py) so vacuum() tests never
touch a real database. `archive()` is a documented no-op now that
DuckDB is the sole raw store (see archive.py's module docstring) -- no
double needed for it, just a direct assertion on its return shape.
"""

from __future__ import annotations

import pytest

from conftest import FakePgConnection

import ecolens.warehouse.runner.archive as archive_module
from ecolens.warehouse.runner.archive import VACUUM_TABLES, ArchiveManager
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings


@pytest.fixture
def manager() -> ArchiveManager:
    return ArchiveManager(WarehouseRunnerSettings())


class TestArchive:
    def test_is_a_documented_noop(self, manager: ArchiveManager):
        result = manager.archive()
        assert result.success is True
        assert result.metrics.get("status") == "skipped"
        assert "no-op" in result.metrics.get("reason", "")
        assert result.rows_affected == 0


class TestVacuumNotConnected:
    def test_skips_when_pg_not_connected(self, manager: ArchiveManager):
        result = manager.vacuum()
        assert result.success is True
        assert result.metrics.get("status") == "skipped"


class TestVacuum:
    def test_sets_autocommit_before_vacuum(self, manager: ArchiveManager, monkeypatch):
        # Regression: VACUUM cannot run inside a transaction block, and
        # psycopg2 opens an implicit transaction unless autocommit is
        # set -- the original script never set it, so vacuum() would
        # have failed against a real database on every run.
        fake_conn = FakePgConnection()
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        assert fake_conn.autocommit_set is True

    def test_runs_vacuum_analyze_on_expected_tables(
        self, manager: ArchiveManager, monkeypatch
    ):
        fake_conn = FakePgConnection()
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        result = manager.vacuum()
        assert result.success is True
        assert result.metrics["tables"] == VACUUM_TABLES
        for table in VACUUM_TABLES:
            assert any(table in stmt for stmt in fake_conn.executed)

    def test_vacuum_error_returns_failed_stage(
        self, manager: ArchiveManager, monkeypatch
    ):
        fake_conn = FakePgConnection(raises=RuntimeError("boom"))
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        result = manager.vacuum()
        assert result.success is False
        assert "boom" in (result.error or "")

    def test_pg_connect_failure_leaves_pg_none(
        self, manager: ArchiveManager, monkeypatch
    ):
        def failing_connect(**kwargs):
            raise ConnectionError("down")

        monkeypatch.setattr(archive_module.psycopg2, "connect", failing_connect)
        manager.connect_pg()
        assert manager._pg is None


class TestClose:
    def test_close_resets_pg_connection(self, manager: ArchiveManager, monkeypatch):
        fake_conn = FakePgConnection()
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        manager.close()
        assert manager._pg is None
        assert fake_conn.closed is True
