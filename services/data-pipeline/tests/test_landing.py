import io
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from app.core.config import get_settings
from app.service.pipeline import landing

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_df_to_parquet_bytes_roundtrips():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    body = landing.df_to_parquet_bytes(df)
    roundtrip = pd.read_parquet(io.BytesIO(body))

    pd.testing.assert_frame_equal(df, roundtrip)


async def test_land_to_s3_uploads_body_to_configured_bucket(monkeypatch):
    put_object = AsyncMock()

    class FakeS3Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def put_object(self, **kwargs):
            return await put_object(**kwargs)

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeS3Client()

    monkeypatch.setattr(landing, "_s3_session", lambda: FakeSession())

    await landing.land_to_s3("some/key.parquet", b"hello")

    put_object.assert_awaited_once()
    _, kwargs = put_object.call_args
    assert kwargs["Bucket"] == get_settings().s3_bucket
    assert kwargs["Key"] == "some/key.parquet"
    assert kwargs["Body"] == b"hello"


async def test_s3_get_bytes_downloads_and_reads_the_body(monkeypatch):
    class FakeBody:
        async def read(self):
            return b"the file contents"

    get_object = AsyncMock(return_value={"Body": FakeBody()})

    class FakeS3Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_object(self, **kwargs):
            return await get_object(**kwargs)

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeS3Client()

    monkeypatch.setattr(landing, "_s3_session", lambda: FakeSession())

    body = await landing.s3_get_bytes("raw/bom/foo.parquet")

    assert body == b"the file contents"
    _, kwargs = get_object.call_args
    assert kwargs["Bucket"] == get_settings().s3_bucket
    assert kwargs["Key"] == "raw/bom/foo.parquet"


async def test_s3_get_bytes_honours_an_explicit_bucket_override(monkeypatch):
    class FakeBody:
        async def read(self):
            return b""

    get_object = AsyncMock(return_value={"Body": FakeBody()})

    class FakeS3Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_object(self, **kwargs):
            return await get_object(**kwargs)

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeS3Client()

    monkeypatch.setattr(landing, "_s3_session", lambda: FakeSession())

    await landing.s3_get_bytes("key", bucket="other-bucket")

    _, kwargs = get_object.call_args
    assert kwargs["Bucket"] == "other-bucket"


async def test_list_s3_keys_returns_the_keys_from_the_response(monkeypatch):
    list_objects_v2 = AsyncMock(
        return_value={
            "Contents": [
                {"Key": "raw/bom/a.parquet"},
                {"Key": "raw/bom/b.parquet"},
            ]
        }
    )

    class FakeS3Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_objects_v2(self, **kwargs):
            return await list_objects_v2(**kwargs)

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeS3Client()

    monkeypatch.setattr(landing, "_s3_session", lambda: FakeSession())

    keys = await landing.list_s3_keys("raw/bom/")

    assert keys == ["raw/bom/a.parquet", "raw/bom/b.parquet"]
    _, kwargs = list_objects_v2.call_args
    assert kwargs["Bucket"] == get_settings().s3_bucket
    assert kwargs["Prefix"] == "raw/bom/"


async def test_list_s3_keys_returns_empty_list_when_prefix_has_no_objects(monkeypatch):
    list_objects_v2 = AsyncMock(return_value={})  # no "Contents" key at all

    class FakeS3Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_objects_v2(self, **kwargs):
            return await list_objects_v2(**kwargs)

    class FakeSession:
        def client(self, *args, **kwargs):
            return FakeS3Client()

    monkeypatch.setattr(landing, "_s3_session", lambda: FakeSession())

    keys = await landing.list_s3_keys("raw/nothing-here/")

    assert keys == []


async def test_land_to_postgres_blob_upserts_into_landing_blobs():
    execute = AsyncMock()

    class FakeSession:
        async def execute(self, *args, **kwargs):
            return await execute(*args, **kwargs)

    await landing.land_to_postgres_blob(FakeSession(), "raw/thing/a.parquet", b"data")

    execute.assert_awaited_once()
    stmt, params = execute.call_args.args
    assert "meta._landing_blobs" in str(stmt)
    assert "ON CONFLICT" in str(stmt)
    assert params == {"key": "raw/thing/a.parquet", "body": b"data"}


async def test_postgres_blob_get_bytes_returns_the_stored_body():
    class FakeResult:
        def first(self):
            return (b"the bytes",)

    class FakeSession:
        async def execute(self, *args, **kwargs):
            return FakeResult()

    body = await landing.postgres_blob_get_bytes(FakeSession(), "some/key.parquet")

    assert body == b"the bytes"


async def test_postgres_blob_get_bytes_raises_key_error_when_missing():
    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        async def execute(self, *args, **kwargs):
            return FakeResult()

    with pytest.raises(KeyError):
        await landing.postgres_blob_get_bytes(FakeSession(), "missing/key.parquet")


async def test_list_postgres_blob_keys_filters_by_prefix():
    class FakeResult:
        def __iter__(self):
            return iter([("raw/bom/a.parquet",), ("raw/bom/b.parquet",)])

    class FakeSession:
        async def execute(self, stmt, params):
            self.params = params
            return FakeResult()

    session = FakeSession()
    keys = await landing.list_postgres_blob_keys(session, "raw/bom/")

    assert keys == ["raw/bom/a.parquet", "raw/bom/b.parquet"]
    assert session.params == {"pattern": "raw/bom/%"}


async def test_land_to_mongodb_blob_upserts_by_id(monkeypatch):
    update_one = AsyncMock()

    class FakeCollection:
        async def update_one(self, *args, **kwargs):
            return await update_one(*args, **kwargs)

    monkeypatch.setattr(landing, "_mongo_collection", lambda: FakeCollection())

    await landing.land_to_mongodb_blob("raw/thing/a.parquet", b"data")

    update_one.assert_awaited_once()
    filter_, update = update_one.call_args.args
    assert filter_ == {"_id": "raw/thing/a.parquet"}
    assert update["$set"]["body"] == b"data"
    assert update_one.call_args.kwargs == {"upsert": True}


async def test_mongodb_blob_get_bytes_returns_the_stored_body(monkeypatch):
    class FakeCollection:
        async def find_one(self, *args, **kwargs):
            return {"_id": "some/key.parquet", "body": b"the bytes"}

    monkeypatch.setattr(landing, "_mongo_collection", lambda: FakeCollection())

    body = await landing.mongodb_blob_get_bytes("some/key.parquet")

    assert body == b"the bytes"


async def test_mongodb_blob_get_bytes_raises_key_error_when_missing(monkeypatch):
    class FakeCollection:
        async def find_one(self, *args, **kwargs):
            return None

    monkeypatch.setattr(landing, "_mongo_collection", lambda: FakeCollection())

    with pytest.raises(KeyError):
        await landing.mongodb_blob_get_bytes("missing/key.parquet")


async def test_list_mongodb_blob_keys_filters_by_prefix(monkeypatch):
    class FakeCursor:
        def sort(self, *args, **kwargs):
            return self

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for doc in [{"_id": "raw/bom/a.parquet"}, {"_id": "raw/bom/b.parquet"}]:
                yield doc

    class FakeCollection:
        def find(self, filter_, projection):
            self.filter_ = filter_
            self.projection = projection
            return FakeCursor()

    collection = FakeCollection()
    monkeypatch.setattr(landing, "_mongo_collection", lambda: collection)

    keys = await landing.list_mongodb_blob_keys("raw/bom/")

    assert keys == ["raw/bom/a.parquet", "raw/bom/b.parquet"]
    assert collection.filter_ == {"_id": {"$regex": "^raw/bom/"}}


async def test_land_dispatches_to_mongodb_backend(monkeypatch):
    class FakeSettings:
        landing_backend = "mongodb"
        mongodb_db = "ecolens"

    land_to_mongodb_blob = AsyncMock()
    monkeypatch.setattr(landing, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(landing, "land_to_mongodb_blob", land_to_mongodb_blob)

    uri = await landing.land(None, "raw/thing/a.parquet", b"data")

    land_to_mongodb_blob.assert_awaited_once_with("raw/thing/a.parquet", b"data")
    assert uri == "mongodb://ecolens.landing_blobs/raw/thing/a.parquet"


async def test_land_dispatches_to_s3_backend(monkeypatch):
    class FakeSettings:
        landing_backend = "s3"
        s3_bucket = "ecolens"

    land_to_s3 = AsyncMock()
    monkeypatch.setattr(landing, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(landing, "land_to_s3", land_to_s3)

    uri = await landing.land(None, "raw/thing/a.parquet", b"data")

    land_to_s3.assert_awaited_once_with("raw/thing/a.parquet", b"data")
    assert uri == "s3://ecolens/raw/thing/a.parquet"


async def test_land_dispatches_to_postgres_backend(monkeypatch):
    class FakeSettings:
        landing_backend = "postgres"
        s3_bucket = "ecolens"

    land_to_postgres_blob = AsyncMock()
    monkeypatch.setattr(landing, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(landing, "land_to_postgres_blob", land_to_postgres_blob)

    session = object()
    uri = await landing.land(session, "raw/thing/a.parquet", b"data")

    land_to_postgres_blob.assert_awaited_once_with(
        session, "raw/thing/a.parquet", b"data"
    )
    assert uri == "postgres://meta._landing_blobs/raw/thing/a.parquet"


async def test_get_landed_bytes_dispatches_by_backend(monkeypatch):
    class FakeSettings:
        landing_backend = "postgres"

    postgres_blob_get_bytes = AsyncMock(return_value=b"bytes")
    monkeypatch.setattr(landing, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(landing, "postgres_blob_get_bytes", postgres_blob_get_bytes)

    session = object()
    body = await landing.get_landed_bytes(session, "some/key.parquet")

    postgres_blob_get_bytes.assert_awaited_once_with(session, "some/key.parquet")
    assert body == b"bytes"


async def test_list_landed_keys_dispatches_by_backend(monkeypatch):
    class FakeSettings:
        landing_backend = "s3"

    list_s3_keys = AsyncMock(return_value=["raw/bom/a.parquet"])
    monkeypatch.setattr(landing, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(landing, "list_s3_keys", list_s3_keys)

    keys = await landing.list_landed_keys(None, "raw/bom/")

    list_s3_keys.assert_awaited_once_with("raw/bom/")
    assert keys == ["raw/bom/a.parquet"]


async def test_ping_returns_true_on_a_successful_query():
    class FakeSession:
        async def execute(self, *args, **kwargs):
            return None

    assert await landing.ping(FakeSession()) is True


async def test_ping_returns_false_rather_than_raising():
    class FakeSession:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    assert await landing.ping(FakeSession()) is False


async def test_load_to_postgres_empty_df_short_circuits_without_a_connection():
    result = await landing.load_to_postgres(None, pd.DataFrame(), "sometable")
    assert result == 0


async def test_load_to_postgres_copies_into_staging_then_upserts():
    copy_to_table = AsyncMock()
    execute = AsyncMock(side_effect=["CREATE TABLE", "INSERT 0 2"])

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeDriverConnection:
        async def copy_to_table(self, *args, **kwargs):
            return await copy_to_table(*args, **kwargs)

        async def execute(self, *args, **kwargs):
            return await execute(*args, **kwargs)

        def transaction(self):
            return FakeTransaction()

    class FakeRawConnection:
        async def get_raw_connection(self):
            return MagicMock(driver_connection=FakeDriverConnection())

    class FakeSession:
        async def connection(self):
            return FakeRawConnection()

    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    result = await landing.load_to_postgres(FakeSession(), df, "mytable", schema="raw")

    assert result == 2

    # COPY goes into a throwaway staging table, not the real one directly.
    copy_to_table.assert_awaited_once()
    args, kwargs = copy_to_table.call_args
    assert args[0] != "mytable"
    assert "schema_name" not in kwargs
    assert kwargs["columns"] == ["a", "b"]
    assert kwargs["format"] == "csv"
    assert kwargs["null"] == "\\N"

    # Then an upsert from staging into the real table, skipping duplicates.
    assert execute.await_count == 2
    create_sql = execute.call_args_list[0].args[0]
    assert "CREATE TEMP TABLE" in create_sql
    assert '"raw"."mytable"' in create_sql

    insert_sql = execute.call_args_list[1].args[0]
    assert 'INSERT INTO "raw"."mytable"' in insert_sql
    assert "ON CONFLICT DO NOTHING" in insert_sql


async def test_load_to_postgres_distinguishes_none_from_empty_string():
    # Regression test (ECO-D69): Postgres COPY's CSV-format default null
    # marker is an unquoted empty string, which can't be told apart from
    # a genuine empty-string value. Using `\N` (passed as both `na_rep`
    # on the pandas side and `null` to copy_to_table) fixes that -- prove
    # it by checking the actual CSV bytes sent, not just that *a* value
    # was passed for `null`.
    copy_to_table = AsyncMock()
    execute = AsyncMock(side_effect=["CREATE TABLE", "INSERT 0 2"])

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeDriverConnection:
        async def copy_to_table(self, *args, **kwargs):
            return await copy_to_table(*args, **kwargs)

        async def execute(self, *args, **kwargs):
            return await execute(*args, **kwargs)

        def transaction(self):
            return FakeTransaction()

    class FakeRawConnection:
        async def get_raw_connection(self):
            return MagicMock(driver_connection=FakeDriverConnection())

    class FakeSession:
        async def connection(self):
            return FakeRawConnection()

    df = pd.DataFrame({"a": [1, None], "b": ["x", ""]})

    await landing.load_to_postgres(FakeSession(), df, "mytable")

    _, kwargs = copy_to_table.call_args
    csv_bytes = kwargs["source"].read()
    csv_text = csv_bytes.decode("utf-8")
    assert csv_text == "1.0,x\n\\N,\n"
    assert kwargs["null"] == "\\N"


async def test_land_and_load_lands_then_loads_and_returns_uri_and_row_count(
    monkeypatch,
):
    calls = []

    async def fake_land(session, key, body):
        calls.append(("land", key))
        return f"postgres://meta._landing_blobs/{key}"

    async def fake_load_to_postgres(session, df, table, schema="raw"):
        calls.append(("load", table, schema))
        return len(df)

    monkeypatch.setattr(landing, "land", fake_land)
    monkeypatch.setattr(landing, "load_to_postgres", fake_load_to_postgres)

    df = pd.DataFrame({"a": [1]})
    landed_uri, rows_loaded = await landing.land_and_load(
        None, df, "t", s3_key_prefix="raw/thing", schema="raw"
    )

    assert rows_loaded == 1
    assert landed_uri.startswith("postgres://meta._landing_blobs/raw/thing/")
    assert landed_uri.endswith(".parquet")
    assert calls[0][0] == "land"
    assert calls[0][1].startswith("raw/thing/")
    assert calls[1] == ("load", "t", "raw")


async def test_land_and_load_empty_df_skips_landing_and_postgres(monkeypatch):
    calls = []
    monkeypatch.setattr(landing, "land", lambda *a: calls.append("land"))
    monkeypatch.setattr(
        landing, "load_to_postgres", lambda *a, **k: calls.append("load")
    )

    s3_uri, rows_loaded = await landing.land_and_load(
        None, pd.DataFrame(), "t", s3_key_prefix="raw/thing"
    )

    assert (s3_uri, rows_loaded) == ("", 0)
    assert calls == []
