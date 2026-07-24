"""Tests for ecolens.forecasting.data (ECO-109).

`TrainingSetLoader.fetch()` opens its own `asyncpg.connect()` (a single
connection, not a pool -- it's a one-shot batch read, not a live
request path), so it's faked here by monkeypatching `asyncpg.connect`
itself rather than reusing the repo's pool-shaped `FakeAsyncpgPool`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from ecolens.config import Settings
from ecolens.forecasting.data import TrainingSetLoader, latest_snapshot, load_snapshot
from ecolens.warehouse.api.settings import WarehouseApiSettings


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        return self._rows

    async def close(self) -> None:
        self.closed = True


def _install_fake_connect(monkeypatch, rows: list[dict[str, Any]]) -> FakeConn:
    conn = FakeConn(rows)

    async def fake_connect(**kwargs: Any) -> FakeConn:
        return conn

    monkeypatch.setattr("ecolens.forecasting.data.asyncpg.connect", fake_connect)
    return conn


SAMPLE_ROWS = [
    {
        "ts_30": pd.Timestamp("2026-01-01T00:00:00Z"),
        "region": "NSW1",
        "demand_mw": 5000.0,
    },
    {
        "ts_30": pd.Timestamp("2026-01-01T00:30:00Z"),
        "region": "NSW1",
        "demand_mw": 5010.0,
    },
]


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_a_dataframe(self, monkeypatch):
        conn = _install_fake_connect(monkeypatch, SAMPLE_ROWS)
        loader = TrainingSetLoader(
            warehouse_settings=WarehouseApiSettings(), settings=Settings()
        )  # type: ignore[call-arg]
        df = await loader.fetch()
        assert len(df) == 2
        assert list(df["region"]) == ["NSW1", "NSW1"]
        assert conn.closed is True

    @pytest.mark.asyncio
    async def test_fetch_with_regions_filters_via_query_param(self, monkeypatch):
        conn = _install_fake_connect(monkeypatch, SAMPLE_ROWS)
        loader = TrainingSetLoader(
            warehouse_settings=WarehouseApiSettings(), settings=Settings()
        )  # type: ignore[call-arg]
        await loader.fetch(regions=("NSW1", "VIC1"))
        query, args = conn.fetch_calls[0]
        assert "where region = any($1::text[])" in query
        assert args == (["NSW1", "VIC1"],)

    @pytest.mark.asyncio
    async def test_fetch_without_regions_has_no_where_clause(self, monkeypatch):
        conn = _install_fake_connect(monkeypatch, SAMPLE_ROWS)
        loader = TrainingSetLoader(
            warehouse_settings=WarehouseApiSettings(), settings=Settings()
        )  # type: ignore[call-arg]
        await loader.fetch()
        query, args = conn.fetch_calls[0]
        assert "where" not in query
        assert args == ()

    @pytest.mark.asyncio
    async def test_connection_closed_even_on_error(self, monkeypatch):
        conn = FakeConn(SAMPLE_ROWS)

        async def failing_fetch(query: str, *args: Any) -> list[dict[str, Any]]:
            raise RuntimeError("boom")

        conn.fetch = failing_fetch  # type: ignore[method-assign]

        async def fake_connect(**kwargs: Any) -> FakeConn:
            return conn

        monkeypatch.setattr("ecolens.forecasting.data.asyncpg.connect", fake_connect)
        loader = TrainingSetLoader(
            warehouse_settings=WarehouseApiSettings(), settings=Settings()
        )  # type: ignore[call-arg]
        with pytest.raises(RuntimeError, match="boom"):
            await loader.fetch()
        assert conn.closed is True


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_writes_parquet_and_returns_metadata(
        self, monkeypatch, tmp_path
    ):
        _install_fake_connect(monkeypatch, SAMPLE_ROWS)
        settings = Settings(training_snapshot_dir=tmp_path)  # type: ignore[call-arg]
        loader = TrainingSetLoader(
            warehouse_settings=WarehouseApiSettings(), settings=settings
        )  # type: ignore[call-arg]

        snap = await loader.snapshot()
        assert snap.row_count == 2
        assert snap.regions == ("NSW1",)
        assert snap.path.exists()

        reloaded = load_snapshot(snap.path)
        assert len(reloaded) == 2

    @pytest.mark.asyncio
    async def test_snapshot_with_no_rows_returns_empty_regions(
        self, monkeypatch, tmp_path
    ):
        _install_fake_connect(monkeypatch, [])
        settings = Settings(training_snapshot_dir=tmp_path)  # type: ignore[call-arg]
        loader = TrainingSetLoader(
            warehouse_settings=WarehouseApiSettings(), settings=settings
        )  # type: ignore[call-arg]
        snap = await loader.snapshot()
        assert snap.row_count == 0
        assert snap.regions == ()


class TestLatestSnapshot:
    def test_returns_none_for_empty_dir(self, tmp_path):
        assert latest_snapshot(tmp_path) is None

    def test_returns_the_most_recent_file(self, tmp_path):
        (tmp_path / "ml_features_demand_v1_20260101T000000Z.parquet").write_text("a")
        (tmp_path / "ml_features_demand_v1_20260201T000000Z.parquet").write_text("b")
        latest = latest_snapshot(tmp_path)
        assert latest is not None
        assert "20260201" in latest.name
