"""Tests for ecolens_forecast_api.settings.ForecastApiSettings."""

from __future__ import annotations

from ecolens_forecast_api.settings import (
    ForecastApiSettings,
    get_forecast_api_settings,
)


class TestDefaults:
    def test_default_port_is_8003(self):
        assert ForecastApiSettings().api_port == 8003

    def test_default_valid_regions_has_six_entries(self):
        assert set(ForecastApiSettings().valid_regions) == {
            "NSW1",
            "QLD1",
            "VIC1",
            "SA1",
            "TAS1",
            "WEM",
        }

    def test_cache_disabled_by_default(self):
        assert ForecastApiSettings().redis_url is None

    def test_api_key_unset_by_default(self):
        assert ForecastApiSettings().api_key is None

    def test_default_horizon_matches_lag_depth(self):
        assert ForecastApiSettings().default_horizon_slots == 48
        assert ForecastApiSettings().max_horizon_slots == 48


class TestEnvOverride:
    def test_env_prefix_overrides_pg_host(self, monkeypatch):
        monkeypatch.setenv("FORECAST_PG_HOST", "db.internal")
        assert ForecastApiSettings().pg_host == "db.internal"

    def test_env_prefix_overrides_api_port(self, monkeypatch):
        monkeypatch.setenv("FORECAST_API_PORT", "9999")
        assert ForecastApiSettings().api_port == 9999


class TestCachedSingleton:
    def test_get_forecast_api_settings_returns_same_instance(self):
        assert get_forecast_api_settings() is get_forecast_api_settings()
