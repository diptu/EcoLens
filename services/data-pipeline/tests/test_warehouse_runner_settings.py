"""Tests for ecolens.warehouse.runner.settings.WarehouseRunnerSettings."""

from __future__ import annotations

from datetime import timedelta

from ecolens.warehouse.runner.settings import (
    WarehouseRunnerSettings,
    get_warehouse_runner_settings,
)


class TestDefaults:
    def test_dbt_path_resolves_to_the_real_dbt_project_dir(self):
        settings = WarehouseRunnerSettings()
        assert settings.dbt_path.name == "dbt_project"
        assert settings.dbt_path.parent.name == "warehouse"

    def test_log_dir_is_relative_not_absolute(self):
        # Regression: an absolute container-only default (e.g.
        # /var/log/ecolens) crashes with a read-only-filesystem error
        # on a local dev machine -- see the bom/holidays cache_dir fix.
        assert not WarehouseRunnerSettings().log_dir.is_absolute()

    def test_dbt_target_defaults_to_prod(self):
        assert WarehouseRunnerSettings().dbt_target == "prod"

    def test_dbt_threads_defaults_to_one(self):
        assert WarehouseRunnerSettings().dbt_threads == 1

    def test_freshness_thresholds(self):
        settings = WarehouseRunnerSettings()
        assert settings.freshness_threshold_aemo == timedelta(minutes=45)
        assert settings.freshness_threshold_bom == timedelta(hours=2)
        assert settings.freshness_threshold_holidays == timedelta(days=7)

    def test_max_null_pct_is_a_fraction(self):
        settings = WarehouseRunnerSettings()
        assert 0 < settings.max_null_pct < 1


class TestEnvOverride:
    def test_env_prefix_overrides_pg_host(self, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_RUNNER_PG_HOST", "warehouse.internal")
        assert WarehouseRunnerSettings().pg_host == "warehouse.internal"

    def test_env_prefix_overrides_dbt_target(self, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_RUNNER_DBT_TARGET", "staging")
        assert WarehouseRunnerSettings().dbt_target == "staging"


class TestCachedSingleton:
    def test_get_warehouse_runner_settings_returns_same_instance(self):
        assert get_warehouse_runner_settings() is get_warehouse_runner_settings()
