"""forecast-api runtime configuration.

Mirrors `data-pipeline`'s `app.core.config.Settings` in shape (same env
var names/defaults where both services need the same infra —
`DATABASE_URL`, `REDIS_URL`, `MLFLOW_TRACKING_URI` — so one `.env` file
configures both), but is its own independent `Settings` class: the two
services are separate Python packages, each installed into their own
venv (see this package's `__init__.py`), and don't share code beyond
what's deliberately duplicated (`models/ml.py`, `service/ml/features.py`
— see their own docstrings).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    api_port: int = 8000
    api_cors_origins: list[str] = ["*"]

    database_url_env: str | None = Field(default=None, validation_alias="DATABASE_URL")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ecolens"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    redis_url_env: str | None = Field(default=None, validation_alias="REDIS_URL")
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_registry_model_name: str = "lstm_demand"
    # How often the background task checks MLflow for a newer Production
    # version (`README.md`: "forecast-api hot-reloads it on the next
    # request... just a watch on the MLflow registry").
    model_reload_interval_seconds: float = 60.0

    forecast_cache_ttl_seconds: int = 60
    emissions_cache_ttl_seconds: int = 60
    emissions_ytd_cache_ttl_seconds: int = 300
    footprint_cache_ttl_seconds: int = 300
    # `WS /v1/stream/emissions` (`README.md`'s API table: "Server-sent
    # stream, 5-min updates").
    stream_interval_seconds: float = 300.0

    @property
    def database_url(self) -> str:
        if self.database_url_env:
            url = self.database_url_env
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            url = url.replace("sslmode=", "ssl=")
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_url_env:
            return self.redis_url_env
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
