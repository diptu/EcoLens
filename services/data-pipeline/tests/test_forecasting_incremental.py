"""Tests for ecolens.forecasting.training.incremental (year-by-year
chunked training). Real MLflow (SQLite + local artifact dir under
tmp_path, same pattern as test_forecasting_registry.py) and real
train_model()/build_windowed_dataset() -- only `TrainingSetLoader.fetch`
is mocked, since a real Postgres warehouse is out of scope for a unit
test.
"""

from __future__ import annotations

from datetime import date

import mlflow
import numpy as np
import pandas as pd
import pytest

from ecolens.config import Settings
from ecolens.forecasting.data import TrainingSetLoader
from ecolens.forecasting.features import FEATURE_COLUMNS
from ecolens.forecasting.mlops.registry import ModelRegistry
from ecolens.forecasting.training.incremental import run_incremental_chunk


def _learnable_snapshot(*, n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame({"ts_30": ts, "region": "NSW1"})
    t = np.arange(n)
    df["demand_mw"] = 5000 + 300 * np.sin(2 * np.pi * t / 48) + rng.normal(0, 20, n)
    for col in FEATURE_COLUMNS:
        if col == "demand_mw":
            continue
        df[col] = (
            rng.integers(0, 2, size=n)
            if col in ("is_holiday", "is_weekend")
            else rng.normal(size=n)
        )
    return df


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    s = Settings(  # type: ignore[call-arg]
        mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
        mlflow_experiment_name="test_incremental",
        mlflow_registered_model_name="test_incremental_model",
        model_registry_alias="production",
        model_train_epochs=2,
        model_hidden_size=8,
        model_num_layers=1,
        model_batch_size=16,
    )
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    mlflow.set_experiment(s.mlflow_experiment_name)
    return s


def _mock_fetch(monkeypatch, snapshots_by_call: list[pd.DataFrame]) -> list[tuple]:
    """Each call to TrainingSetLoader.fetch returns the next snapshot in
    `snapshots_by_call`, in order. Returns the list of (since, until)
    args each call was made with, for assertions.
    """
    calls: list[tuple] = []
    remaining = list(snapshots_by_call)

    async def fake_fetch(self, regions=None, *, since=None, until=None):
        calls.append((since, until))
        return remaining.pop(0)

    monkeypatch.setattr(TrainingSetLoader, "fetch", fake_fetch)
    return calls


class TestFirstChunk:
    @pytest.mark.asyncio
    async def test_trains_fresh_with_no_prior_run_id(self, settings, monkeypatch):
        _mock_fetch(monkeypatch, [_learnable_snapshot(seed=0)])

        result = await run_incremental_chunk(
            date(2023, 1, 1), date(2023, 12, 31), settings=settings
        )

        assert result.train_result.run_id
        assert result.prior_run_id is None
        assert result.chunk_start == "2023-01-01"
        assert result.chunk_end == "2023-12-31"
        assert result.registered_version is None  # evaluate_and_promote defaults False

    @pytest.mark.asyncio
    async def test_fetches_the_requested_date_range(self, settings, monkeypatch):
        calls = _mock_fetch(monkeypatch, [_learnable_snapshot(seed=0)])

        await run_incremental_chunk(
            date(2023, 1, 1), date(2023, 12, 31), settings=settings
        )

        since, until = calls[0]
        assert since.isoformat() == "2023-01-01T00:00:00+00:00"
        assert until.isoformat() == "2024-01-01T00:00:00+00:00"  # exclusive, +1 day

    @pytest.mark.asyncio
    async def test_tags_the_run_with_chunk_bounds(self, settings, monkeypatch):
        _mock_fetch(monkeypatch, [_learnable_snapshot(seed=0)])

        result = await run_incremental_chunk(
            date(2023, 1, 1), date(2023, 12, 31), settings=settings
        )

        run = mlflow.get_run(result.train_result.run_id)
        assert run.data.tags["chunk_start"] == "2023-01-01"
        assert run.data.tags["chunk_end"] == "2023-12-31"
        assert "parent_run_id" not in run.data.tags


class TestContinuationChunk:
    @pytest.mark.asyncio
    async def test_continues_from_prior_checkpoint(self, settings, monkeypatch):
        _mock_fetch(
            monkeypatch, [_learnable_snapshot(seed=0), _learnable_snapshot(seed=1)]
        )

        first = await run_incremental_chunk(
            date(2023, 1, 1), date(2023, 12, 31), settings=settings
        )
        second = await run_incremental_chunk(
            date(2024, 1, 1),
            date(2024, 12, 31),
            prior_run_id=first.train_result.run_id,
            settings=settings,
        )

        assert second.prior_run_id == first.train_result.run_id
        run = mlflow.get_run(second.train_result.run_id)
        assert run.data.tags["parent_run_id"] == first.train_result.run_id

    @pytest.mark.asyncio
    async def test_reuses_the_first_chunks_scaler_not_a_fresh_fit(
        self, settings, monkeypatch
    ):
        _mock_fetch(
            monkeypatch, [_learnable_snapshot(seed=0), _learnable_snapshot(seed=1)]
        )

        first = await run_incremental_chunk(
            date(2023, 1, 1), date(2023, 12, 31), settings=settings
        )
        second = await run_incremental_chunk(
            date(2024, 1, 1),
            date(2024, 12, 31),
            prior_run_id=first.train_result.run_id,
            settings=settings,
        )

        registry = ModelRegistry(settings=settings)
        first_scaler = registry.load_checkpoint(first.train_result.run_id).scaler
        second_scaler = registry.load_checkpoint(second.train_result.run_id).scaler
        assert np.array_equal(first_scaler.mean, second_scaler.mean)
        assert np.array_equal(first_scaler.std, second_scaler.std)

    @pytest.mark.asyncio
    async def test_mismatched_architecture_raises(self, settings, monkeypatch):
        _mock_fetch(
            monkeypatch, [_learnable_snapshot(seed=0), _learnable_snapshot(seed=1)]
        )
        first = await run_incremental_chunk(
            date(2023, 1, 1), date(2023, 12, 31), settings=settings
        )

        different_arch_settings = settings.model_copy(update={"model_hidden_size": 32})
        with pytest.raises(ValueError, match="architecture doesn't match"):
            await run_incremental_chunk(
                date(2024, 1, 1),
                date(2024, 12, 31),
                prior_run_id=first.train_result.run_id,
                settings=different_arch_settings,
            )


class TestEvaluateAndPromote:
    @pytest.mark.asyncio
    async def test_registers_and_promotes_when_requested(self, settings, monkeypatch):
        _mock_fetch(monkeypatch, [_learnable_snapshot(seed=0)])

        result = await run_incremental_chunk(
            date(2023, 1, 1),
            date(2023, 12, 31),
            evaluate_and_promote=True,
            settings=settings,
        )

        assert result.registered_version is not None
        assert result.promoted is True  # first version always promotes
        assert result.promotion_reason

    @pytest.mark.asyncio
    async def test_skips_registration_by_default(self, settings, monkeypatch):
        _mock_fetch(monkeypatch, [_learnable_snapshot(seed=0)])

        result = await run_incremental_chunk(
            date(2023, 1, 1), date(2023, 12, 31), settings=settings
        )

        assert result.registered_version is None
        assert result.promoted is None
        registry = ModelRegistry(settings=settings)
        assert registry.list_versions() == []
