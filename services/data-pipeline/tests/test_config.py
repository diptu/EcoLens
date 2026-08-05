from pathlib import Path

import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_cover_all_groups():
    # `_env_file=None` bypasses the real `.env` for this instantiation --
    # this test is about `Settings`' own field defaults, not whatever a
    # developer's local `.env` happens to override (e.g.
    # MLFLOW_TRACKING_URI=:5001, commonly set locally to dodge macOS
    # AirPlay's port-5000 collision). Deleting `MLFLOW_TRACKING_URI` from
    # `os.environ` alone doesn't help here, unlike `database_url_env`'s
    # `monkeypatch.setenv(..., "")` trick below -- this field has no
    # truthy-check fallback to its default, and pydantic-settings' env-
    # file source reads `.env` directly regardless of `os.environ`.
    s = Settings(_env_file=None)
    assert s.api_port == 8001
    assert s.postgres_db == "ecolens"
    assert s.redis_db == 0
    assert s.s3_bucket == "ecolens"
    assert s.mlflow_tracking_uri == "http://localhost:5000"
    assert set(s.bom_stations) == {"NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"}
    assert s.bom_stations["NSW1"] == "066037"
    assert s.model_train_epochs == 50
    assert s.model_train_lr == pytest.approx(1e-3)
    assert s.default_lookback_minutes == 30
    assert s.circuit_breaker_failure_threshold == 5
    assert s.circuit_breaker_reset_timeout == pytest.approx(60.0)
    assert s.hostname
    assert s.dbt_auto_build_interval_seconds == pytest.approx(300.0)


def test_database_url_assembles_asyncpg_dsn(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", ""
    )  # else the real .env's DATABASE_URL would win
    s = Settings(
        postgres_user="u",
        postgres_password="p",
        postgres_host="h",
        postgres_port=1,
        postgres_db="d",
    )
    assert s.database_url == "postgresql+asyncpg://u:p@h:1/d"


def test_database_url_env_overrides_decomposed_fields(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/d")
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://u:p@h:1/d"


def test_database_url_env_normalizes_sslmode_to_ssl_for_asyncpg(monkeypatch):
    # asyncpg doesn't understand `sslmode` (libpq/psycopg's query-param
    # name) -- Neon and most managed Postgres providers hand you a DSN
    # with `sslmode=require`, which fails at connect time with
    # `connect() got an unexpected keyword argument 'sslmode'` unless
    # rewritten to `ssl=require`.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/d?sslmode=require")
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://u:p@h:1/d?ssl=require"


def test_redis_url_env_overrides_decomposed_fields(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "rediss://default:secret@my-redis.upstash.io:6380")
    s = Settings()
    assert s.redis_url == "rediss://default:secret@my-redis.upstash.io:6380"


def test_redis_url_assembles_dsn():
    s = Settings(redis_host="h", redis_port=1, redis_db=2)
    assert s.redis_url == "redis://h:1/2"


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("API_PORT", "9999")
    assert get_settings().api_port == 9999


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_dbt_project_dir_is_absolute_regardless_of_cwd():
    """Regression: used to be the bare relative string `"dbt/ecolens"`,
    which only resolved correctly when the process's CWD happened to be
    `services/data-pipeline` -- `make dbt-build` runs `uv run --package
    data-pipeline ...` from the repo root instead (unlike forecast-api's
    Makefile targets, which use `--directory`), so dbt itself rejected
    it: `Error: Invalid value for '--project-dir': Path 'dbt/ecolens'
    does not exist.`"""
    s = Settings(_env_file=None)
    path = Path(s.dbt_project_dir)
    assert path.is_absolute()
    assert path.name == "ecolens"
    assert path.parent.name == "dbt"
    assert path.exists()


def test_env_file_is_this_packages_own_env_regardless_of_cwd():
    """Regression: a bare relative `".env"` in `model_config` resolves
    against the *process's* CWD, not this file's location -- from the
    repo root (`make dbt-build`'s CWD) that silently loaded the repo
    root's own `.env` instead of `services/data-pipeline/.env`, which in
    this codebase's real dev setup points at a different, largely empty
    database. No assertion on *contents* here (that's every other test
    in this file) -- just that the configured path is this package's
    own, not a bare relative string that CWD could hijack."""
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).is_absolute()
    assert Path(env_file).parent.name == "data-pipeline"


def test_dbt_postgres_env_derives_from_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/d")
    s = Settings()

    assert s.dbt_postgres_env == {
        "POSTGRES_HOST": "h",
        "POSTGRES_PORT": "1",
        "POSTGRES_USER": "u",
        "POSTGRES_PASSWORD": "p",
        "POSTGRES_DB": "d",
    }


def test_dbt_postgres_env_falls_back_to_decomposed_fields(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")  # else the real .env's would win
    s = Settings(
        postgres_user="u2",
        postgres_password="p2",
        postgres_host="h2",
        postgres_port=2,
        postgres_db="d2",
    )

    assert s.dbt_postgres_env == {
        "POSTGRES_HOST": "h2",
        "POSTGRES_PORT": "2",
        "POSTGRES_USER": "u2",
        "POSTGRES_PASSWORD": "p2",
        "POSTGRES_DB": "d2",
    }
