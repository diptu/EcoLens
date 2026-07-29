"""Tests for ecolens.warehouse.service.archive.ArchiveManager.

Uses a fake psycopg2-shaped double (conftest.py) so these never touch
a real database.
"""

from __future__ import annotations

import pytest

from conftest import FakePgConnection

import ecolens.warehouse.service.archive as archive_module
from ecolens.warehouse.service.archive import (
    RAW_RETENTION_TABLES,
    VACUUM_TABLES,
    ArchiveManager,
)
from ecolens.warehouse.core.runner_settings import WarehouseRunnerSettings


@pytest.fixture
def manager() -> ArchiveManager:
    return ArchiveManager(WarehouseRunnerSettings())


class TestArchiveNotConnected:
    def test_skips_when_pg_not_connected(self, manager: ArchiveManager):
        result = manager.archive()
        assert result.success is True
        assert result.metrics.get("status") == "skipped"


class TestArchive:
    def test_trims_every_raw_retention_table(self, manager: ArchiveManager, monkeypatch):
        fake_conn = FakePgConnection(rowcount=7)
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        result = manager.archive()
        assert result.success is True
        assert result.rows_affected == 7 * len(RAW_RETENTION_TABLES)
        for table, ts_col in RAW_RETENTION_TABLES:
            assert any(
                table in stmt and ts_col in stmt for stmt in fake_conn.executed
            )

    def test_never_touches_aemo_holidays(self, manager: ArchiveManager, monkeypatch):
        fake_conn = FakePgConnection(rowcount=1)
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        manager.archive()
        assert not any("aemo_holidays" in stmt for stmt in fake_conn.executed)

    def test_uses_configured_retention_window(self, manager: ArchiveManager, monkeypatch):
        manager.settings.raw_retention_days = 14
        fake_conn = FakePgConnection(rowcount=0)
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        result = manager.archive()
        assert result.metrics["retention_days"] == 14
        assert any("14 days" in stmt for stmt in fake_conn.executed)

    def test_archive_error_returns_failed_stage(self, manager: ArchiveManager, monkeypatch):
        fake_conn = FakePgConnection(raises=RuntimeError("boom"))
        monkeypatch.setattr(archive_module.psycopg2, "connect", lambda **kw: fake_conn)
        manager.connect_pg()
        result = manager.archive()
        assert result.success is False
        assert "boom" in (result.error or "")


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
