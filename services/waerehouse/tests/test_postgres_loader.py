from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from app.loaders import postgres_loader

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeDriverConnection:
    def __init__(self, copy_to_table, execute):
        self._copy_to_table = copy_to_table
        self._execute = execute

    async def copy_to_table(self, *args, **kwargs):
        return await self._copy_to_table(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        return await self._execute(*args, **kwargs)

    def transaction(self):
        return _FakeTransaction()


class _FakeRawConnection:
    def __init__(self, driver_connection):
        self._driver_connection = driver_connection

    async def get_raw_connection(self):
        return MagicMock(driver_connection=self._driver_connection)


class _FakeSession:
    def __init__(self, driver_connection):
        self._driver_connection = driver_connection

    async def connection(self):
        return _FakeRawConnection(self._driver_connection)


async def test_empty_dataframe_short_circuits_without_a_connection():
    result = await postgres_loader.load_to_postgres(None, pd.DataFrame(), "sometable")

    assert result == 0


async def test_copies_into_a_staging_table_then_upserts_into_the_real_one():
    copy_to_table = AsyncMock()
    execute = AsyncMock(side_effect=["CREATE TABLE", "INSERT 0 2"])
    session = _FakeSession(_FakeDriverConnection(copy_to_table, execute))

    df = pd.DataFrame({"ts": ["2026-01-01"], "region": ["NSW1"]})
    df = pd.concat([df, df], ignore_index=True)
    df["region"] = ["NSW1", "QLD1"]

    result = await postgres_loader.load_to_postgres(
        session, df, "aemo_nem_dispatch", schema="raw"
    )

    assert result == 2

    copy_to_table.assert_awaited_once()
    args, kwargs = copy_to_table.call_args
    assert args[0] != "aemo_nem_dispatch"  # goes into a throwaway staging table
    assert kwargs["columns"] == ["ts", "region"]
    assert kwargs["format"] == "csv"
    assert kwargs["null"] == "\\N"

    assert execute.await_count == 2
    create_sql = execute.call_args_list[0].args[0]
    assert "CREATE TEMP TABLE" in create_sql
    assert '"raw"."aemo_nem_dispatch"' in create_sql

    insert_sql = execute.call_args_list[1].args[0]
    assert 'INSERT INTO "raw"."aemo_nem_dispatch"' in insert_sql
    assert "ON CONFLICT DO NOTHING" in insert_sql


async def test_none_is_distinguished_from_empty_string_in_the_csv_payload():
    captured = {}

    async def copy_to_table(*args, source=None, **kwargs):
        captured["csv_bytes"] = source.read()

    execute = AsyncMock(side_effect=["CREATE TABLE", "INSERT 0 1"])
    session = _FakeSession(_FakeDriverConnection(copy_to_table, execute))

    df = pd.DataFrame({"a": [None], "b": [""]})

    await postgres_loader.load_to_postgres(session, df, "t")

    csv_text = captured["csv_bytes"].decode()
    assert csv_text.strip() == r"\N,"


async def test_raises_when_no_driver_connection_is_available():
    class _NoDriverRawConnection:
        async def get_raw_connection(self):
            return MagicMock(driver_connection=None)

    class _NoDriverSession:
        async def connection(self):
            return _NoDriverRawConnection()

    df = pd.DataFrame({"a": [1]})

    with pytest.raises(RuntimeError, match="no underlying asyncpg connection"):
        await postgres_loader.load_to_postgres(_NoDriverSession(), df, "t")
