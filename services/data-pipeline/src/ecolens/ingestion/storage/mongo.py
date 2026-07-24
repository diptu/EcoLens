"""Async MongoDB client + bulk upsert for the ingestion layer.

See INGESTION.md for the overall design. Docs are upserted via each
source's unique compound key (`MongoSettings.unique_key_for_source`) so
retries with the same fetch are idempotent instead of creating duplicates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import UpdateOne

from ecolens.ingestion.storage.settings import get_mongo_settings


@lru_cache(maxsize=1)
def get_mongo_client() -> AsyncIOMotorClient:
    settings = get_mongo_settings()
    return AsyncIOMotorClient(
        settings.mongo_uri,
        maxPoolSize=settings.mongo_max_pool_size,
        minPoolSize=settings.mongo_min_pool_size,
        serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
        connectTimeoutMS=settings.mongo_connect_timeout_ms,
        socketTimeoutMS=settings.mongo_socket_timeout_ms,
        retryReads=settings.mongo_retry_reads,
        retryWrites=settings.mongo_retry_writes,
    )


def get_db() -> AsyncIOMotorDatabase:
    return get_mongo_client()[get_mongo_settings().mongo_db_name]


async def bulk_upsert(
    db: AsyncIOMotorDatabase,
    source: str,
    docs: list[dict],
    run_id: str,
) -> int:
    """Upsert `docs` into the collection mapped to `source`, stamping ingest metadata.

    Returns the number of documents inserted or modified.
    """
    if not docs:
        return 0

    settings = get_mongo_settings()
    collection_name = settings.collection_for_source(source)
    unique_key = settings.unique_key_for_source(source)
    fetched_at = datetime.now(timezone.utc)

    for doc in docs:
        doc["ingest_run_id"] = run_id
        doc["fetched_at"] = fetched_at
        doc["source"] = source

    operations = [
        UpdateOne(
            {key: doc[key] for key in unique_key},
            {"$set": doc},
            upsert=True,
        )
        for doc in docs
    ]

    chunk_size = settings.mongo_bulk_chunk_size
    collection = db[collection_name]
    upserted_total = 0
    for i in range(0, len(operations), chunk_size):
        chunk = operations[i : i + chunk_size]
        result = await collection.bulk_write(chunk, ordered=settings.mongo_bulk_ordered)
        upserted_total += result.upserted_count + result.modified_count
    return upserted_total


__all__ = ["get_mongo_client", "get_db", "bulk_upsert"]
