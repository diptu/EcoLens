"""Generic S3-compatible object storage client (`TODO.md`'s Storage item:
dashboard static assets + MLflow model-weight artifact backups on
Cloudflare R2).

Resolves to R2 once `Settings.object_storage_configured` is true (a real
R2 API token is present), else falls back to local MinIO -- `Settings.
object_storage_endpoint_url`/`_bucket`/`_access_key`/`_secret_key`
already encode that precedence (see `config.py`). Two concrete callers
today, both in `scripts/`: `upload_assets_to_r2.py` (dashboard
`public/images/*`) and `sync_mlflow_artifacts_to_r2.py` (`.mlflow/
artifacts/**`, a backup/mirror copy -- MLflow's own artifact resolution
for training/serving is untouched, see that script's own docstring for
why). Deliberately separate from `pipeline.landing`'s `land_to_s3`/
`s3_get_bytes`/`list_s3_keys` -- those are the legacy raw-*ingestion*
landing path (MinIO-only, `Settings.s3_*` directly, superseded by
DuckDB staging), a different concern from asset/artifact storage even
though both happen to speak S3.
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
    """Human-readable one-liner for script output -- so running an
    upload script always says plainly whether it just hit real R2 or
    local MinIO, rather than leaving that to be inferred."""
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
    `upload_bytes` -- fine at the file sizes this targets today (dashboard
    images, MLflow artifacts, all well under a few MB each); a genuinely
    large file would want a real multipart upload instead."""
    return await upload_bytes(key, local_path.read_bytes(), bucket=bucket)


async def download_bytes(key: str, bucket: str | None = None) -> bytes:
    settings = get_settings()
    bucket_name = bucket or settings.object_storage_bucket
    async with _session().client("s3", **_client_kwargs()) as s3:
        response = await s3.get_object(Bucket=bucket_name, Key=key)
        return await response["Body"].read()


async def list_keys(prefix: str, bucket: str | None = None) -> list[str]:
    """Same single-page (<=1000 keys) simplification as `landing.
    list_s3_keys` -- fine for the asset/artifact volumes this targets
    today (hundreds of files, not thousands)."""
    settings = get_settings()
    bucket_name = bucket or settings.object_storage_bucket
    async with _session().client("s3", **_client_kwargs()) as s3:
        response = await s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    return [obj["Key"] for obj in response.get("Contents", [])]


async def object_exists(key: str, bucket: str | None = None) -> bool:
    """Used by the upload scripts to skip re-uploading a key that's
    already there, so a re-run after a partial failure is cheap."""
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
