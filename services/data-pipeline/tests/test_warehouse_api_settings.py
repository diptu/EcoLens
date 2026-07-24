"""Tests for ecolens.warehouse.api.settings.WarehouseApiSettings."""

from __future__ import annotations

from ecolens.warehouse.api.settings import (
    WarehouseApiSettings,
    get_warehouse_api_settings,
)


class TestDefaults:
    def test_default_port_is_8002(self):
        assert WarehouseApiSettings().api_port == 8002

    def test_default_valid_regions_has_six_entries(self):
        assert set(WarehouseApiSettings().valid_regions) == {
            "NSW1",
            "QLD1",
            "VIC1",
            "SA1",
            "TAS1",
            "WEM",
        }

    def test_cache_disabled_by_default(self):
        assert WarehouseApiSettings().redis_url is None

    def test_api_key_unset_by_default(self):
        assert WarehouseApiSettings().api_key is None


class TestEnvOverride:
    def test_env_prefix_overrides_pg_host(self, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_PG_HOST", "db.internal")
        assert WarehouseApiSettings().pg_host == "db.internal"

    def test_env_prefix_overrides_api_port(self, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_API_PORT", "9999")
        assert WarehouseApiSettings().api_port == 9999


class TestCachedSingleton:
    def test_get_warehouse_api_settings_returns_same_instance(self):
        assert get_warehouse_api_settings() is get_warehouse_api_settings()
