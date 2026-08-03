"""Async MongoDB client for the data-pipeline service.

Lazily built from `app.core.config.get_settings().mongodb_url` — backs
`pipeline.landing`'s `Settings.landing_backend == "mongodb"` raw-landing
option (README's "fetched API data lands in MongoDB" requirement).
"""

from __future__ import annotations

from functools import lru_cache

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from app.core.config import get_settings


@lru_cache
def get_mongo_client() -> AsyncMongoClient:
    return AsyncMongoClient(get_settings().mongodb_url)


def get_landing_collection() -> AsyncCollection:
    """The collection `pipeline.landing`'s MongoDB backend reads/writes —
    one document per landed blob, keyed by `_id` (the same `key` the S3/
    Postgres backends use)."""
    settings = get_settings()
    return get_mongo_client()[settings.mongodb_db]["landing_blobs"]


async def close_mongo() -> None:
    """Close the MongoDB client's connection pool (call on service shutdown)."""
    await get_mongo_client().close()
