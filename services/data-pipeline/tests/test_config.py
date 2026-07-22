"""Tests for ecolens.config.Settings / get_settings."""

from __future__ import annotations

from pathlib import Path

from ecolens.config import Settings, get_settings


class TestGetSettings:
    def test_cached_singleton(self):
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second
        get_settings.cache_clear()


class TestSettingsDefaults:
    def test_default_field_values(self, monkeypatch):
        # Isolate from any ambient env vars / .env so defaults are exercised.
        monkeypatch.chdir(Path(__file__).parent)  # no .env file here
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        assert settings.service_name == "ecolens-data-pipeline"
        assert settings.env == "dev"
        assert settings.log_level == "INFO"
        assert settings.mongo_db_name == "ecolens"
        assert settings.oe_api_key is None
        assert settings.model_lookback == 48
        assert settings.optuna_n_trials == 50
        assert settings.conformal_alpha == 0.1

    def test_bom_stations_default_factory(self, monkeypatch):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.bom_stations["NSW1"] == "066037"
        assert settings.bom_stations["WEM"] == "009225"

    def test_api_cors_origins_default_factory(self):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.api_cors_origins == ["http://localhost:3000"]

    def test_derived_paths(self):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.dbt_project_dir == Path("/app/dbt/ecolens")
        assert settings.migrations_dir.name == "migrations"

    def test_oe_api_key_overridable_via_constructor(self):
        settings = Settings(_env_file=None, oe_api_key="my-test-key")  # type: ignore[call-arg]
        assert settings.oe_api_key == "my-test-key"
