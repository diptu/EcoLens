import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_cover_all_groups():
    s = Settings()
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
