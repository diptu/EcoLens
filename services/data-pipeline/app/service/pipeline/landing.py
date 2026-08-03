"""LEGACY raw-landing backends (MongoDB, S3/MinIO, Postgres-blob), plus
`load_to_postgres`/`ping`, which are still very much in use.

Superseded as of `overview.md` §2: the live ingest path
(`pipeline.tasks._common.standard_run`) now stages each fetch in DuckDB
(`pipeline.duckdb_staging`) and publishes a RabbitMQ event instead of
calling `land_and_load` — see `TODO.md`'s Ingestion section. Everything
below this docstring still works and is still tested
(`tests/test_landing.py`), just no longer wired into the hot path:

- `land_to_s3`/`s3_get_bytes`/`list_s3_keys`, the Postgres-blob trio
  `land_to_postgres_blob`/`postgres_blob_get_bytes`/`list_postgres_blob_keys`,
  and the MongoDB trio `land_to_mongodb_blob`/`mongodb_blob_get_bytes`/
  `list_mongodb_blob_keys` are all independent — any of them can still be
  used on its own. `land`/`get_landed_bytes`/`list_landed_keys` dispatch
  to whichever trio `Settings.landing_backend` selects.
- `load_to_postgres` — the actual `raw.*` bulk load — is NOT legacy.
  `pipeline.warehouse_sync`'s RabbitMQ consumer calls it directly; it's
  the Postgres half of the new design too, just invoked from a different
  caller now.
- `ping` — plain Postgres readiness probe, unrelated to landing at all.
- `land_and_load` — the old round-trip (land a Parquet audit copy, then
  `load_to_postgres`) that `standard_run` used to call in one step.
  Still callable directly (e.g. for manual replay), just not part of the
  automated ingest flow anymore.
"""

from __future__ import annotations

import io
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import aioboto3
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

# Postgres COPY's own CSV-format default null representation is an
# unquoted empty string — which is indistinguishable from a genuine
# empty-string value in a text column. Using `\N` (the TEXT-format
# convention) instead, on both the pandas and asyncpg sides, disambiguates
# "this was NULL" from "this was an empty string" (task.md's Layer-3
# table documents this exact choice).
_NULL_MARKER = r"\N"


def _s3_session() -> aioboto3.Session:
    return aioboto3.Session()


async def land_to_s3(key: str, body: bytes) -> None:
    """Upload `body` (typically Parquet-encoded, via `df_to_parquet_bytes`)
    to the landing bucket at `key`."""
    settings = get_settings()
    async with _s3_session().client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    ) as s3:
        await s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=body)


async def s3_get_bytes(key: str, bucket: str | None = None) -> bytes:
    """Download a single object's bytes from the landing bucket.

    Used to replay a landed Parquet file into Postgres after a partial
    failure (S3 succeeded, `load_to_postgres` didn't) —
    `pipeline/tasks/task.md`'s "Failure Modes & Recovery" mode 4.
    """
    settings = get_settings()
    bucket_name = bucket or settings.s3_bucket
    async with _s3_session().client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    ) as s3:
        response = await s3.get_object(Bucket=bucket_name, Key=key)
        return await response["Body"].read()


async def list_s3_keys(prefix: str, bucket: str | None = None) -> list[str]:
    """List object keys under `prefix` in the landing bucket.

    A single `list_objects_v2` call — capped at S3's default 1000-key
    page, not paginated further. That's a deliberate simplification for
    the backfill/replay use case this exists for (a source's landed
    files over a few weeks), not an oversight: if a prefix ever holds
    more than 1000 objects, this silently returns only the first page.
    """
    settings = get_settings()
    bucket_name = bucket or settings.s3_bucket
    async with _s3_session().client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    ) as s3:
        response = await s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    return [obj["Key"] for obj in response.get("Contents", [])]


async def land_to_postgres_blob(session: AsyncSession, key: str, body: bytes) -> None:
    """Upsert `body` into `meta._landing_blobs`, keyed by `key`.

    Postgres-backed alternative to `land_to_s3` (`Settings.landing_backend
    == "postgres"`, migration `0013_meta_landing_blobs.sql`) — the same
    audit-trail role, no MinIO/S3 dependency.
    """
    await session.execute(
        text(
            """
            INSERT INTO meta._landing_blobs (key, body)
            VALUES (:key, :body)
            ON CONFLICT (key) DO UPDATE SET body = EXCLUDED.body, created_at = now()
            """
        ),
        {"key": key, "body": body},
    )


async def postgres_blob_get_bytes(session: AsyncSession, key: str) -> bytes:
    """Fetch a single landed blob's bytes by `key`. Raises `KeyError` if
    it's not there — mirrors `s3_get_bytes` raising on a missing object."""
    result = await session.execute(
        text("SELECT body FROM meta._landing_blobs WHERE key = :key"),
        {"key": key},
    )
    row = result.first()
    if row is None:
        raise KeyError(key)
    return row[0]


async def list_postgres_blob_keys(session: AsyncSession, prefix: str) -> list[str]:
    """List landed blob keys starting with `prefix`, for replay/backfill —
    the Postgres-backend counterpart to `list_s3_keys`."""
    result = await session.execute(
        text(
            "SELECT key FROM meta._landing_blobs WHERE key LIKE :pattern ORDER BY key"
        ),
        {"pattern": f"{prefix}%"},
    )
    return [row[0] for row in result]


def _mongo_collection() -> Any:
    """Indirection point so tests can monkeypatch the MongoDB collection
    without a real cluster — mirrors `_s3_session()`'s role for S3."""
    from app.db.mongo import get_landing_collection

    return get_landing_collection()


async def land_to_mongodb_blob(key: str, body: bytes) -> None:
    """Upsert `body` into the `landing_blobs` collection, keyed by `_id`.

    MongoDB-backed alternative to `land_to_s3`/`land_to_postgres_blob`
    (`Settings.landing_backend == "mongodb"`, the default — README's
    "fetched API data lands in MongoDB" requirement).
    """
    await _mongo_collection().update_one(
        {"_id": key},
        {"$set": {"body": body, "created_at": datetime.now(UTC)}},
        upsert=True,
    )


async def mongodb_blob_get_bytes(key: str) -> bytes:
    """Fetch a single landed blob's bytes by `key`. Raises `KeyError` if
    it's not there — mirrors `s3_get_bytes`/`postgres_blob_get_bytes`."""
    doc = await _mongo_collection().find_one({"_id": key})
    if doc is None:
        raise KeyError(key)
    return bytes(doc["body"])


async def list_mongodb_blob_keys(prefix: str) -> list[str]:
    """List landed blob keys starting with `prefix`, for replay/backfill —
    the MongoDB-backend counterpart to `list_s3_keys`/`list_postgres_blob_keys`."""
    cursor = (
        _mongo_collection()
        .find({"_id": {"$regex": f"^{re.escape(prefix)}"}}, {"_id": 1})
        .sort("_id", 1)
    )
    return [doc["_id"] async for doc in cursor]


async def land(session: AsyncSession, key: str, body: bytes) -> str:
    """Land `body` at `key` via `Settings.landing_backend`.

    Returns a URI identifying where it landed (`s3://...`,
    `postgres://meta._landing_blobs/...`, or
    `mongodb://<db>.landing_blobs/...`), for logging.
    """
    settings = get_settings()
    if settings.landing_backend == "s3":
        await land_to_s3(key, body)
        return f"s3://{settings.s3_bucket}/{key}"
    if settings.landing_backend == "mongodb":
        await land_to_mongodb_blob(key, body)
        return f"mongodb://{settings.mongodb_db}.landing_blobs/{key}"
    await land_to_postgres_blob(session, key, body)
    return f"postgres://meta._landing_blobs/{key}"


async def get_landed_bytes(session: AsyncSession, key: str) -> bytes:
    """Fetch a previously-`land`ed blob's bytes, from whichever backend
    `Settings.landing_backend` currently selects."""
    settings = get_settings()
    if settings.landing_backend == "s3":
        return await s3_get_bytes(key)
    if settings.landing_backend == "mongodb":
        return await mongodb_blob_get_bytes(key)
    return await postgres_blob_get_bytes(session, key)


async def list_landed_keys(session: AsyncSession, prefix: str) -> list[str]:
    """List landed keys under `prefix`, from whichever backend
    `Settings.landing_backend` currently selects."""
    settings = get_settings()
    if settings.landing_backend == "s3":
        return await list_s3_keys(prefix)
    if settings.landing_backend == "mongodb":
        return await list_mongodb_blob_keys(prefix)
    return await list_postgres_blob_keys(session, prefix)


def df_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """Serialise `df` to Parquet bytes, ready for `land`/`land_to_s3`."""
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    return buffer.getvalue()


async def load_to_postgres(
    session: AsyncSession, df: pd.DataFrame, table: str, schema: str = "raw"
) -> int:
    """Bulk-load `df` into `schema.table` via asyncpg's COPY (CSV format).

    Ingestion is expected to be safely re-runnable (`task.md`'s recovery
    playbook re-triggers sources manually for catch-up, and overlapping
    `lookback_minutes` windows re-fetch rows we already have), so a plain
    COPY straight into the target table isn't good enough — it dies on
    the first row that collides with an existing `(pk)`. COPY instead
    into a throwaway temp table (still fast, still COPY), then
    `INSERT ... ON CONFLICT DO NOTHING` from there into the real table.
    Rows already landed by an earlier run are silently skipped.

    Returns the number of rows actually inserted (excluding skipped
    duplicates). A no-op (returns 0) for an empty DataFrame, without
    opening a connection.
    """
    if df.empty:
        return 0

    raw_connection = await session.connection()
    driver_connection = (await raw_connection.get_raw_connection()).driver_connection
    if driver_connection is None:
        raise RuntimeError("no underlying asyncpg connection")

    columns = list(df.columns)
    csv_text = df.to_csv(index=False, header=False, na_rep=_NULL_MARKER)
    buffer = io.BytesIO(csv_text.encode("utf-8"))

    staging_table = f"_load_{uuid.uuid4().hex[:12]}"
    quoted_columns = ", ".join(f'"{c}"' for c in columns)

    # A bare `driver_connection.execute()` auto-commits as its own
    # transaction — `ON COMMIT DROP` would drop the staging table before
    # `copy_to_table` ever saw it. One explicit transaction keeps
    # create/copy/insert on the same server-side session.
    # `schema`/`table` come only from this module's own two internal
    # callers (`warehouse_sync.py`, this file's own `ingest_and_land`),
    # always literal source-registry identifiers -- never request input --
    # and `staging_table`/`quoted_columns` are generated here, not passed
    # in. Postgres identifiers can't be bound params, so this has to be
    # string-built; nosec B608 applies to all three statements below.
    async with driver_connection.transaction():
        await driver_connection.execute(
            f'CREATE TEMP TABLE "{staging_table}" '  # nosec B608
            f'(LIKE "{schema}"."{table}" INCLUDING DEFAULTS) ON COMMIT DROP'
        )
        await driver_connection.copy_to_table(
            staging_table,
            source=buffer,
            columns=columns,
            format="csv",
            null=_NULL_MARKER,
        )
        result = await driver_connection.execute(
            f'INSERT INTO "{schema}"."{table}" ({quoted_columns}) '  # nosec B608
            f'SELECT {quoted_columns} FROM "{staging_table}" '
            "ON CONFLICT DO NOTHING"
        )
    return int(result.split()[-1])


async def ping(session: AsyncSession) -> bool:
    """Cheap Postgres readiness probe (`SELECT 1`).

    Returns `True`/`False` rather than raising — callers (health checks)
    want a boolean, not an exception to handle.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def land_and_load(
    session: AsyncSession,
    df: pd.DataFrame,
    table: str,
    s3_key_prefix: str,
    schema: str = "raw",
) -> tuple[str, int]:
    """Land `df` as Parquet under `s3_key_prefix` (backend per
    `Settings.landing_backend`), then load it into Postgres.

    Returns `(landed_uri, rows_loaded)`. A no-op for an empty DataFrame —
    skips the landing step too, not just the Postgres load — returning
    `("", 0)`.
    """
    if df.empty:
        return "", 0

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    key = f"{s3_key_prefix.rstrip('/')}/{timestamp}-{uuid.uuid4().hex[:8]}.parquet"

    landed_uri = await land(session, key, df_to_parquet_bytes(df))
    rows_loaded = await load_to_postgres(session, df, table, schema=schema)

    return landed_uri, rows_loaded
