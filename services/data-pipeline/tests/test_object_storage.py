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
    def __init__(
        self, put_object=None, get_object=None, list_objects_v2=None, head_object=None
    ):
        self._put_object = put_object or AsyncMock()
        self._get_object = get_object or AsyncMock()
        self._list_objects_v2 = list_objects_v2 or AsyncMock(return_value={})
        self._head_object = head_object or AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def put_object(self, **kwargs):
        return await self._put_object(**kwargs)

    async def get_object(self, **kwargs):
        return await self._get_object(**kwargs)

    async def list_objects_v2(self, **kwargs):
        return await self._list_objects_v2(**kwargs)

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

    uri = await object_storage.upload_bytes("some/key.png", b"hello")

    put_object.assert_awaited_once()
    _, kwargs = put_object.call_args
    assert kwargs["Bucket"] == get_settings().object_storage_bucket
    assert kwargs["Key"] == "some/key.png"
    assert kwargs["Body"] == b"hello"
    assert uri == f"s3://{get_settings().object_storage_bucket}/some/key.png"


async def test_upload_bytes_honours_an_explicit_bucket_override(monkeypatch):
    put_object = AsyncMock()
    _patch_session(monkeypatch, _FakeS3Client(put_object=put_object))

    uri = await object_storage.upload_bytes("k", b"x", bucket="other-bucket")

    assert put_object.call_args.kwargs["Bucket"] == "other-bucket"
    assert uri == "s3://other-bucket/k"


async def test_upload_file_reads_local_bytes_and_uploads(monkeypatch, tmp_path):
    put_object = AsyncMock()
    _patch_session(monkeypatch, _FakeS3Client(put_object=put_object))

    local = tmp_path / "model.pth"
    local.write_bytes(b"weights")

    await object_storage.upload_file(local, "mlflow/artifacts/model.pth")

    assert put_object.call_args.kwargs["Body"] == b"weights"
    assert put_object.call_args.kwargs["Key"] == "mlflow/artifacts/model.pth"


async def test_download_bytes_reads_the_response_body(monkeypatch):
    class FakeBody:
        async def read(self):
            return b"the file contents"

    get_object = AsyncMock(return_value={"Body": FakeBody()})
    _patch_session(monkeypatch, _FakeS3Client(get_object=get_object))

    body = await object_storage.download_bytes("assets/dashboard/images/earth.jpg")

    assert body == b"the file contents"
    assert get_object.call_args.kwargs["Key"] == "assets/dashboard/images/earth.jpg"


async def test_list_keys_returns_just_the_key_strings(monkeypatch):
    list_objects_v2 = AsyncMock(
        return_value={"Contents": [{"Key": "a/1.png"}, {"Key": "a/2.png"}]}
    )
    _patch_session(monkeypatch, _FakeS3Client(list_objects_v2=list_objects_v2))

    keys = await object_storage.list_keys("a/")

    assert keys == ["a/1.png", "a/2.png"]


async def test_list_keys_empty_prefix_returns_empty_list(monkeypatch):
    _patch_session(
        monkeypatch, _FakeS3Client(list_objects_v2=AsyncMock(return_value={}))
    )

    assert await object_storage.list_keys("nothing/here/") == []


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


def test_active_backend_summary_reports_minio_when_r2_not_configured():
    summary = object_storage.active_backend_summary()

    assert "MinIO" in summary
    assert get_settings().object_storage_bucket in summary
