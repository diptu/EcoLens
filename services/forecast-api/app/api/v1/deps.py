from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import get_redis
from app.core.config import Settings, get_settings
from app.db.session import get_log_session, get_session
from app.service.ml.energy_registry import EnergyModelRegistry
from app.service.ml.registry import ModelRegistry


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session


async def get_log_db() -> AsyncIterator[AsyncSession]:
    """Same shape as `get_db`, bound to `db.session.get_log_session`
    instead -- for routes that only ever touch the real "logger" tables
    (`meta._training_log` writes, `meta.anomalies`/`meta._dbt_build_log`
    reads, 2026-08-12)."""
    async with get_log_session() as session:
        yield session


def get_app_settings() -> Settings:
    return get_settings()


def get_redis_client() -> Redis:
    return get_redis()


def get_model_registry(request: Request) -> ModelRegistry:
    registry: ModelRegistry = request.app.state.model_registry
    return registry


def get_energy_model_registry(request: Request) -> EnergyModelRegistry:
    registry: EnergyModelRegistry = request.app.state.energy_model_registry
    return registry
