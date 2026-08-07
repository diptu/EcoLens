from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.db import object_storage

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


async def test_upload_file_reads_local_bytes_and_uploads(monkeypatch, tmp_path):
    put_object = AsyncMock()
    _patch_session(monkeypatch, _FakeS3Client(put_object=put_object))

    local = tmp_path / "export.parquet"
    local.write_bytes(b"cold storage bytes")

    await object_storage.upload_file(local, "coldstorage/export.parquet")

    assert put_object.call_args.kwargs["Body"] == b"cold storage bytes"


async def test_download_bytes_reads_the_response_body(monkeypatch):
    class FakeBody:
        async def read(self):
            return b"the staged file contents"

    get_object = AsyncMock(return_value={"Body": FakeBody()})
    _patch_session(monkeypatch, _FakeS3Client(get_object=get_object))

    body = await object_storage.download_bytes("staging/bom_observations-run-1.duckdb")

    assert body == b"the staged file contents"
    assert get_object.call_args.kwargs["Key"] == "staging/bom_observations-run-1.duckdb"
    assert get_object.call_args.kwargs["Bucket"] == get_settings().object_storage_bucket


async def test_download_bytes_honours_an_explicit_bucket_override(monkeypatch):
    class FakeBody:
        async def read(self):
            return b"x"

    get_object = AsyncMock(return_value={"Body": FakeBody()})
    _patch_session(monkeypatch, _FakeS3Client(get_object=get_object))

    await object_storage.download_bytes("some/key", bucket="other-bucket")

    assert get_object.call_args.kwargs["Bucket"] == "other-bucket"


async def test_object_exists_true_when_head_object_succeeds(monkeypatch):
    _patch_session(monkeypatch, _FakeS3Client(head_object=AsyncMock(return_value={})))

    assert await object_storage.object_exists("some/key") is True


async def test_object_exists_false_on_404(monkeypatch):
    from botocore.exceptions import ClientError

    error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    _patch_session(monkeypatch, _FakeS3Client(head_object=AsyncMock(side_effect=error)))

    assert await object_storage.object_exists("missing/key") is False
