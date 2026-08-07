"""Generic S3-compatible object storage client (Cloudflare R2, local
MinIO fallback) — this service's own copy of `services/ingestion`'s
identical module, same account/bucket.

`upload_bytes`/`upload_file`/`object_exists` back `retention.
cold_storage` (upload-only — nothing in this service ever reads
cold-storage *exports* back). `download_bytes` is for a different
concern: `consumers.landed_events.sync_landed_event`'s fallback when
the `duckdb_staging` shared volume it'd otherwise share with
`services/ingestion` isn't actually shared (that producer running on a
different machine) — see `db.duckdb_client.read_run_with_fallback`'s
own docstring.
"""

from __future__ import annotations

import os
from pathlib import Path

import aioboto3
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.config import get_settings

# R2 rejects (or at least doesn't advertise support for) the newer AWS
# SDK default of sending `x-amz-checksum-*` request headers / requiring
# response checksum validation on every call -- same fix `services/
# ingestion`'s identical module applies, for the same reason.
os.environ.setdefault("AWS_REQUEST_CHECKSUM_CALCULATION", "when_required")
os.environ.setdefault("AWS_RESPONSE_CHECKSUM_VALIDATION", "when_required")


def _session() -> aioboto3.Session:
    return aioboto3.Session()


def _client_kwargs() -> dict[str, str]:
    settings = get_settings()
    return {
        "endpoint_url": settings.object_storage_endpoint_url,
        "aws_access_key_id": settings.object_storage_access_key,
        "aws_secret_access_key": settings.object_storage_secret_key,
    }


def active_backend_summary() -> str:
    settings = get_settings()
    backend = (
        "Cloudflare R2"
        if settings.object_storage_configured
        else "local MinIO (R2 not configured)"
    )
    return f"{backend} -- endpoint={settings.object_storage_endpoint_url} bucket={settings.object_storage_bucket}"


async def upload_bytes(key: str, body: bytes, bucket: str | None = None) -> str:
    """Upload `body` to `key`. Returns the `s3://bucket/key` URI it landed at."""
    settings = get_settings()
    bucket_name = bucket or settings.object_storage_bucket
    async with _session().client("s3", **_client_kwargs()) as s3:
        await s3.put_object(Bucket=bucket_name, Key=key, Body=body)
    return f"s3://{bucket_name}/{key}"


async def upload_file(local_path: Path, key: str, bucket: str | None = None) -> str:
    return await upload_bytes(key, local_path.read_bytes(), bucket=bucket)


async def download_bytes(key: str, bucket: str | None = None) -> bytes:
    settings = get_settings()
    bucket_name = bucket or settings.object_storage_bucket
    async with _session().client("s3", **_client_kwargs()) as s3:
        response = await s3.get_object(Bucket=bucket_name, Key=key)
        return await response["Body"].read()


async def object_exists(key: str, bucket: str | None = None) -> bool:
    settings = get_settings()
    bucket_name = bucket or settings.object_storage_bucket
    async with _session().client("s3", **_client_kwargs()) as s3:
        try:
            await s3.head_object(Bucket=bucket_name, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise
