from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.service import object_storage

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeS3Client:
    def __init__(self, put_object=None, get_object=None, head_object=None):
        self._put_object = put_object or AsyncMock()
        self._get_object = get_object or AsyncMock()
        self._head_object = head_object or AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def put_object(self, **kwargs):
        return await self._put_object(**kwargs)

    async def get_object(self, **kwargs):
        return await self._get_object(**kwargs)

    async def head_object(self, **kwargs):
        return await self._head_object(**kwargs)


def _patch_session(monkeypatch, client: _FakeS3Client) -> None:
    class FakeSession:
        def client(self, *args, **kwargs):
            return client

    monkeypatch.setattr(object_storage, "_session", lambda: FakeSession())


async def test_upload_bytes_targets_configured_bucket(monkeypatch):
    put_object = AsyncMock()
    _patch_session(monkeypatch, _FakeS3Client(put_object=put_object))

    uri = await object_storage.upload_bytes("some/key.duckdb", b"hello")

    put_object.assert_awaited_once()
    _, kwargs = put_object.call_args
    assert kwargs["Bucket"] == get_settings().object_storage_bucket
    assert kwargs["Key"] == "some/key.duckdb"
    assert kwargs["Body"] == b"hello"
    assert uri == f"s3://{get_settings().object_storage_bucket}/some/key.duckdb"


async def test_upload_bytes_honours_an_explicit_bucket_override(monkeypatch):
    put_object = AsyncMock()
    _patch_session(monkeypatch, _FakeS3Client(put_object=put_object))

    uri = await object_storage.upload_bytes("k", b"x", bucket="other-bucket")

    assert put_object.call_args.kwargs["Bucket"] == "other-bucket"
    assert uri == "s3://other-bucket/k"


async def test_upload_file_reads_local_bytes_and_uploads(monkeypatch, tmp_path):
    put_object = AsyncMock()
    _patch_session(monkeypatch, _FakeS3Client(put_object=put_object))

    local = tmp_path / "bom_observations-run-1.duckdb"
    local.write_bytes(b"staged-dataframe-bytes")

    await object_storage.upload_file(local, "staging/bom_observations-run-1.duckdb")

    assert put_object.call_args.kwargs["Body"] == b"staged-dataframe-bytes"
    assert put_object.call_args.kwargs["Key"] == "staging/bom_observations-run-1.duckdb"


async def test_download_bytes_reads_the_response_body(monkeypatch):
    class FakeBody:
        async def read(self):
            return b"the file contents"

    get_object = AsyncMock(return_value={"Body": FakeBody()})
    _patch_session(monkeypatch, _FakeS3Client(get_object=get_object))

    body = await object_storage.download_bytes("staging/bom_observations-run-1.duckdb")

    assert body == b"the file contents"
    assert get_object.call_args.kwargs["Key"] == "staging/bom_observations-run-1.duckdb"


async def test_object_exists_true_when_head_object_succeeds(monkeypatch):
    _patch_session(monkeypatch, _FakeS3Client(head_object=AsyncMock(return_value={})))

    assert await object_storage.object_exists("some/key") is True


async def test_object_exists_false_on_404(monkeypatch):
    error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    _patch_session(monkeypatch, _FakeS3Client(head_object=AsyncMock(side_effect=error)))

    assert await object_storage.object_exists("missing/key") is False


async def test_object_exists_reraises_non_404_errors(monkeypatch):
    error = ClientError({"Error": {"Code": "403"}}, "HeadObject")
    _patch_session(monkeypatch, _FakeS3Client(head_object=AsyncMock(side_effect=error)))

    with pytest.raises(ClientError):
        await object_storage.object_exists("forbidden/key")


def test_active_backend_summary_reports_minio_when_r2_not_configured(monkeypatch):
    # Explicit isolation, not ambient `.env` state -- `object_storage_
    # configured` reflects whatever's actually in the environment this
    # test runs in (real R2 creds are genuinely configured in this
    # service's own local `.env` as of 2026-08-05), so asserting "MinIO"
    # without overriding that would make this test's outcome depend on
    # unrelated local machine/deployment state.
    monkeypatch.setenv("CLOUDFLARESTORAGE_ACCESS_KEY_ID", "")
    monkeypatch.setenv("CLOUDFLARESTORAGE_SECRET_ACCESS_KEY", "")
    get_settings.cache_clear()
    try:
        summary = object_storage.active_backend_summary()

        assert "MinIO" in summary
        assert get_settings().object_storage_bucket in summary
    finally:
        get_settings.cache_clear()


def test_active_backend_summary_reports_r2_when_configured(monkeypatch):
    monkeypatch.setenv("CLOUDFLARESTORAGE_ACCESS_KEY_ID", "fake-key-id")
    monkeypatch.setenv("CLOUDFLARESTORAGE_SECRET_ACCESS_KEY", "fake-secret")
    monkeypatch.setenv("CLOUDFLARESTORAGE_ACCOUNT_ID", "fake-account")
    get_settings.cache_clear()
    try:
        summary = object_storage.active_backend_summary()

        assert "Cloudflare R2" in summary
        assert "MinIO" not in summary
    finally:
        get_settings.cache_clear()
