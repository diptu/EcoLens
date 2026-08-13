"""Generic S3-compatible object storage client (`services/ingestion/
TODO.md` Phase 2, "Integrate Cloudflare R2 Staging").

Resolves to R2 once `Settings.object_storage_configured` is true (a real
R2 API token is present), else falls back to local MinIO -- `Settings.
object_storage_endpoint_url`/`_bucket`/`_access_key`/`_secret_key`
already encode that precedence (see `config.py`). Ported from
data-pipeline's identical module (same account/bucket, this service just
uploads under a different key prefix — `pipeline.duckdb_staging.
upload_staged_file` — rather than a separate bucket).
"""

from __future__ import annotations

import os
from pathlib import Path

import aioboto3
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.config import get_settings

# R2 rejects (or at least doesn't advertise support for) the newer AWS
# SDK default of sending `x-amz-checksum-*` request headers / requiring
# response checksum validation on every call (botocore >=1.36's default
# `when_supported`) -- a real, documented S3-compatible-provider
# incompatibility, not hypothetical. `when_required` (only compute/
# validate when the operation actually demands it) is what every
# S3-compatible provider, R2 included, actually accepts. Set once here
# via `setdefault` (not overriding an operator's own explicit choice) --
# botocore reads these from the process environment, not from client
# constructor kwargs, so this has to happen before any client is built,
# not per-call.
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
    """Human-readable one-liner -- so a run always says plainly whether
    it just hit real R2 or local MinIO, rather than leaving that to be
    inferred."""
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
    """Upload a local file's bytes to `key`. Thin wrapper over
    `upload_bytes` -- fine at the file sizes this targets today (a
    single run's staged DuckDB file), not a real multipart upload."""
    return await upload_bytes(key, local_path.read_bytes(), bucket=bucket)


async def download_bytes(key: str, bucket: str | None = None) -> bytes:
    settings = get_settings()
    bucket_name = bucket or settings.object_storage_bucket
    async with _session().client("s3", **_client_kwargs()) as s3:
        response = await s3.get_object(Bucket=bucket_name, Key=key)
        return await response["Body"].read()


async def object_exists(key: str, bucket: str | None = None) -> bool:
    """Used by `upload_staged_file` to skip re-uploading a key that's
    already there (`services/ingestion/TODO.md` Phase 2's "Verify
    Idempotency" item) -- a redelivered/retried publish shouldn't pay for
    a redundant upload."""
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
