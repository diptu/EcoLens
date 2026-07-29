"""Tests for ecolens.forecasting.cli (ECO-119).

`_fetch_and_window` is monkeypatched to a small synthetic dataset in
every test below -- it's the one thing that needs a live warehouse
Postgres, and that's already exercised for real in
`test_forecasting_data.py`. Everything past that point (train, tune,
evaluate, register, promote, fine-tune) runs for real against a local
SQLite MLflow store, so these tests cover the CLI's actual orchestration
logic, not just its argument parsing.
"""

from __future__ import annotations

import mlflow
import numpy as np
import pandas as pd
import pytest

from ecolens.config import Settings, get_settings
from ecolens.forecasting.core import cli
from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.windowing import build_windowed_dataset


def _dataset_raw():
    rng = np.random.default_rng(9)
    n = 300
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


def _dataset():
    return build_windowed_dataset(_dataset_raw(), lookback=48, horizon=48)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.setenv("MLFLOW_REGISTERED_MODEL_NAME", "cli_test_model")
    monkeypatch.setenv("MODEL_TRAIN_EPOCHS", "2")
    monkeypatch.setenv("MODEL_HIDDEN_SIZE", "8")
    monkeypatch.setenv("MODEL_BATCH_SIZE", "32")
    get_settings.cache_clear()
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_experiment(get_settings().mlflow_experiment_name)

    dataset = _dataset()
    fetch_calls: list[dict] = []

    async def fake_fetch_and_window(settings: Settings, *, since=None, scaler=None):
        fetch_calls.append({"since": since, "scaler": scaler})
        return dataset

    monkeypatch.setattr(cli, "_fetch_and_window", fake_fetch_and_window)
    yield fetch_calls
    get_settings.cache_clear()


@pytest.fixture
def cli_env_tft(cli_env, monkeypatch):
    """`cli_env` plus TFT-scoped env vars -- kept separate since the TFT
    path has its own hyperparameters/experiment/registered-model name
    (see config.py's mlflow_*_tft fields), not the LSTM's. Re-clears
    get_settings' cache after setting these, since cli_env's own body
    already called get_settings() once (for mlflow.set_experiment) and
    cached a Settings instance without these overrides.
    """
    monkeypatch.setenv("MODEL_TFT_TRAIN_EPOCHS", "2")
    monkeypatch.setenv("MODEL_TFT_D_MODEL", "8")
    monkeypatch.setenv("MODEL_TFT_NUM_HEADS", "2")
    monkeypatch.setenv("MODEL_TFT_STATIC_DIM", "8")
    monkeypatch.setenv("MODEL_TFT_BATCH_SIZE", "32")
    monkeypatch.setenv("MLFLOW_REGISTERED_MODEL_NAME_TFT", "cli_test_model_tft")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME_TFT", "cli_test_experiment_tft")
    get_settings.cache_clear()
    yield cli_env
    get_settings.cache_clear()


class _FakeTimesFMBackbone:
    def forecast_raw(self, contexts, *, horizon):
        last = contexts[:, -1:]
        p50 = np.repeat(last, horizon, axis=1)
        return p50 - 200.0, p50, p50 + 200.0


@pytest.fixture
def cli_env_timesfm(cli_env, monkeypatch):
    """`cli_env` plus TimesFM-scoped env vars and a monkeypatched
    `FrozenTimesFM` -- `cmd_train_timesfm()` always constructs a real
    backbone when none is passed in (correct for production use), so this
    fixture replaces that class in `train_timesfm`'s own namespace with a
    fake, instant one instead of letting the real ~2GB checkpoint download
    happen in a test.
    """
    monkeypatch.setenv("MODEL_TIMESFM_TRAIN_EPOCHS", "2")
    monkeypatch.setenv("MODEL_TIMESFM_HIDDEN_DIM", "8")
    monkeypatch.setenv("MODEL_TIMESFM_STATIC_DIM", "8")
    monkeypatch.setenv("MODEL_TIMESFM_BATCH_SIZE", "32")
    monkeypatch.setenv("MLFLOW_REGISTERED_MODEL_NAME_TIMESFM", "cli_test_model_timesfm")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME_TIMESFM", "cli_test_experiment_timesfm")
    get_settings.cache_clear()

    from ecolens.forecasting.service.training import (
        online_timesfm as online_timesfm_module,
        train_timesfm as train_timesfm_module,
    )

    # Both modules did `from ..timesfm_backbone import FrozenTimesFM`, so
    # each holds its own already-bound reference -- patching the source
    # module's attribute wouldn't reach either of these local names.
    monkeypatch.setattr(
        train_timesfm_module,
        "FrozenTimesFM",
        lambda settings=None: _FakeTimesFMBackbone(),
    )
    monkeypatch.setattr(
        online_timesfm_module,
        "FrozenTimesFM",
        lambda settings=None: _FakeTimesFMBackbone(),
    )
    yield cli_env
    get_settings.cache_clear()


class TestParseArgs:
    def test_train(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "train"])
        args = cli.parse_args()
        assert args.command == "train"

    def test_tune_with_n_trials(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "tune", "--n-trials", "7"])
        args = cli.parse_args()
        assert args.command == "tune"
        assert args.n_trials == 7

    def test_status(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "status"])
        assert cli.parse_args().command == "status"

    def test_train_tft(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "train-tft"])
        assert cli.parse_args().command == "train-tft"

    def test_train_timesfm(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "train-timesfm"])
        assert cli.parse_args().command == "train-timesfm"

    def test_online_finetune_tft(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "online-finetune-tft"])
        assert cli.parse_args().command == "online-finetune-tft"

    def test_online_finetune_timesfm(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "online-finetune-timesfm"])
        assert cli.parse_args().command == "online-finetune-timesfm"

    def test_train_fuel_ensemble(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["cli.py", "train-fuel-ensemble"])
        assert cli.parse_args().command == "train-fuel-ensemble"


class TestCmdTrain:
    @pytest.mark.asyncio
    async def test_trains_registers_and_promotes(self, cli_env, capsys):
        exit_code = await cli.cmd_train()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "trained version" in out
        assert "promoted=True" in out


class TestCmdTrainTFT:
    @pytest.mark.asyncio
    async def test_trains_registers_and_promotes(self, cli_env_tft, capsys):
        exit_code = await cli.cmd_train_tft()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "trained TFT version" in out
        assert "promoted=True" in out

    @pytest.mark.asyncio
    async def test_registers_under_its_own_model_name_not_the_lstm_s(
        self, cli_env_tft, capsys
    ):
        # Regression guard for the derived-Settings plumbing in
        # cmd_train_tft: if it ever accidentally used the LSTM's
        # ModelRegistry (settings.mlflow_registered_model_name instead of
        # the _tft field), this would either collide with or silently
        # overwrite the LSTM's own "production" alias.
        from ecolens.forecasting.service.mlops.registry import ModelRegistry

        await cli.cmd_train_tft()
        settings = get_settings()
        tft_registry = ModelRegistry(
            settings=settings.model_copy(
                update={
                    "mlflow_registered_model_name": settings.mlflow_registered_model_name_tft
                }
            )
        )
        assert tft_registry.get_by_alias(settings.model_registry_alias) is not None

        lstm_registry = ModelRegistry(settings=settings)
        assert lstm_registry.get_by_alias(settings.model_registry_alias) is None


class TestCmdTrainTimesFM:
    @pytest.mark.asyncio
    async def test_trains_registers_and_promotes(self, cli_env_timesfm, capsys):
        exit_code = await cli.cmd_train_timesfm()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "trained TimesFM version" in out
        assert "promoted=True" in out

    @pytest.mark.asyncio
    async def test_registers_under_its_own_model_name_not_the_lstm_s_or_tft_s(
        self, cli_env_timesfm, capsys
    ):
        from ecolens.forecasting.service.mlops.registry import ModelRegistry

        await cli.cmd_train_timesfm()
        settings = get_settings()
        timesfm_registry = ModelRegistry(
            settings=settings.model_copy(
                update={
                    "mlflow_registered_model_name": settings.mlflow_registered_model_name_timesfm
                }
            )
        )
        assert timesfm_registry.get_by_alias(settings.model_registry_alias) is not None

        lstm_registry = ModelRegistry(settings=settings)
        assert lstm_registry.get_by_alias(settings.model_registry_alias) is None


class TestCmdEvaluate:
    @pytest.mark.asyncio
    async def test_evaluates_the_current_production_model(self, cli_env, capsys):
        await cli.cmd_train()  # seed a production model to evaluate
        exit_code = await cli.cmd_evaluate()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "MAPE=" in out
        assert "coverage=" in out


class TestCmdStatus:
    @pytest.mark.asyncio
    async def test_reports_no_model_before_training(self, cli_env, capsys):
        exit_code = await cli.cmd_status()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "production_version=None" in out

    @pytest.mark.asyncio
    async def test_reports_a_model_after_training(self, cli_env, capsys):
        await cli.cmd_train()
        exit_code = await cli.cmd_status()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "production_version=None" not in out  # a real version is now set


class TestCmdOnlineFinetune:
    @pytest.mark.asyncio
    async def test_fine_tunes_the_current_production_model(self, cli_env, capsys):
        await cli.cmd_train()
        exit_code = await cli.cmd_online_finetune()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "fine-tuned version" in out

    @pytest.mark.asyncio
    async def test_scopes_the_fetch_to_the_buffer_since_last_trained_and_reuses_its_scaler(
        self, cli_env, capsys
    ):
        # Regression guard for root TODO.md's "Fine tuning" section, "feed
        # each run from the new 30-min data buffer accumulated since the
        # previous fine-tune, not the full historical set" -- cli_env's
        # fake _fetch_and_window records every call's since=/scaler=.
        fetch_calls = cli_env
        await cli.cmd_train()
        assert fetch_calls[-1] == {"since": None, "scaler": None}  # full-history train

        await cli.cmd_online_finetune()
        finetune_call = fetch_calls[-1]
        assert finetune_call["since"] is not None
        assert finetune_call["scaler"] is not None

    @pytest.mark.asyncio
    async def test_raises_when_no_production_model_exists_yet(self, cli_env):
        with pytest.raises(RuntimeError, match="no '.*' version registered"):
            await cli.cmd_online_finetune()


class TestCmdOnlineFinetuneTFT:
    @pytest.mark.asyncio
    async def test_fine_tunes_the_current_production_tft(self, cli_env_tft, capsys):
        await cli.cmd_train_tft()
        exit_code = await cli.cmd_online_finetune_tft()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "fine-tuned TFT version" in out

    @pytest.mark.asyncio
    async def test_scopes_the_fetch_to_the_buffer_since_last_trained(
        self, cli_env_tft, capsys
    ):
        fetch_calls = cli_env_tft
        await cli.cmd_train_tft()
        await cli.cmd_online_finetune_tft()
        finetune_call = fetch_calls[-1]
        assert finetune_call["since"] is not None
        assert finetune_call["scaler"] is not None

    @pytest.mark.asyncio
    async def test_raises_when_no_production_tft_exists_yet(self, cli_env_tft):
        with pytest.raises(RuntimeError, match="no TFT '.*' version registered"):
            await cli.cmd_online_finetune_tft()

    @pytest.mark.asyncio
    async def test_does_not_touch_the_lstm_s_production_alias(self, cli_env_tft):
        from ecolens.forecasting.service.mlops.registry import ModelRegistry

        await cli.cmd_train_tft()
        await cli.cmd_online_finetune_tft()
        settings = get_settings()
        lstm_registry = ModelRegistry(settings=settings)
        assert lstm_registry.get_by_alias(settings.model_registry_alias) is None


class TestCmdOnlineFinetuneTimesFM:
    @pytest.mark.asyncio
    async def test_fine_tunes_the_current_production_timesfm(
        self, cli_env_timesfm, capsys
    ):
        await cli.cmd_train_timesfm()
        exit_code = await cli.cmd_online_finetune_timesfm()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "fine-tuned TimesFM version" in out

    @pytest.mark.asyncio
    async def test_scopes_the_fetch_to_the_buffer_since_last_trained(
        self, cli_env_timesfm, capsys
    ):
        fetch_calls = cli_env_timesfm
        await cli.cmd_train_timesfm()
        await cli.cmd_online_finetune_timesfm()
        finetune_call = fetch_calls[-1]
        assert finetune_call["since"] is not None
        assert finetune_call["scaler"] is not None

    @pytest.mark.asyncio
    async def test_raises_when_no_production_timesfm_exists_yet(self, cli_env_timesfm):
        with pytest.raises(RuntimeError, match="no TimesFM '.*' version registered"):
            await cli.cmd_online_finetune_timesfm()


@pytest.fixture
def cli_env_fuel_ensemble(tmp_path, monkeypatch):
    """Own fixture, not `cli_env` -- `cmd_train_fuel_ensemble()` reads
    `FuelTrainingSetLoader` directly (it needs the raw joined mart, not a
    windowed dataset), same reasoning `TestCmdFeatureSelection`'s own
    fixture-free monkeypatch already documents for `TrainingSetLoader`.
    """
    from ecolens.forecasting.model.fuel_ensemble import FUEL_COLUMNS
    from ecolens.forecasting.repository.fuel_training_data import (
        FuelTrainingSetLoader,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.setenv("MLFLOW_REGISTERED_MODEL_NAME_FUEL_ENSEMBLE", "cli_test_fuel")
    monkeypatch.setenv(
        "MLFLOW_EXPERIMENT_NAME_FUEL_ENSEMBLE", "cli_test_fuel_experiment"
    )
    monkeypatch.setenv("MODEL_FUEL_N_ESTIMATORS", "20")
    monkeypatch.setenv("MODEL_FUEL_NUM_LEAVES", "7")
    get_settings.cache_clear()
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")

    rng = np.random.default_rng(17)
    n = 200
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame({"ts_30": ts, "region": "NSW1"})
    for col in FEATURE_COLUMNS:
        df[col] = (
            rng.integers(0, 2, size=n) if col == "is_holiday" else rng.normal(size=n)
        )
    for fuel in FUEL_COLUMNS:
        df[fuel] = rng.normal(loc=50, scale=10, size=n)

    async def fake_fetch(self, regions=None, *, since=None, until=None):
        return df

    monkeypatch.setattr(FuelTrainingSetLoader, "fetch", fake_fetch)
    yield
    get_settings.cache_clear()


class TestCmdTrainFuelEnsemble:
    @pytest.mark.asyncio
    async def test_trains_registers_and_promotes(self, cli_env_fuel_ensemble, capsys):
        exit_code = await cli.cmd_train_fuel_ensemble()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "trained fuel ensemble version" in out
        assert "promoted=True" in out

    @pytest.mark.asyncio
    async def test_registers_under_its_own_model_name(self, cli_env_fuel_ensemble):
        from ecolens.forecasting.service.mlops.registry import ModelRegistry

        await cli.cmd_train_fuel_ensemble()
        settings = get_settings()
        fuel_registry = ModelRegistry(
            settings=settings.model_copy(
                update={
                    "mlflow_registered_model_name": settings.mlflow_registered_model_name_fuel_ensemble
                }
            )
        )
        assert fuel_registry.get_by_alias(settings.model_registry_alias) is not None

        lstm_registry = ModelRegistry(settings=settings)
        assert lstm_registry.get_by_alias(settings.model_registry_alias) is None


class TestCmdTune:
    @pytest.mark.asyncio
    async def test_runs_a_small_study(self, cli_env, capsys):
        exit_code = await cli.cmd_tune(2)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "best params" in out


class TestCmdFeatureSelection:
    @pytest.mark.asyncio
    async def test_prints_a_summary_for_every_step(self, monkeypatch, capsys):
        # cmd_feature_selection() reads TrainingSetLoader directly (not
        # _fetch_and_window -- it needs the raw mart, not a windowed
        # dataset), so it needs its own monkeypatch rather than reusing
        # the cli_env fixture's _fetch_and_window patch. Needs more rows
        # than _dataset_raw()'s 300 -- Step 3's default max_lag=340
        # requires n > 2*max_lag (real ml_features_demand_v1 has ~17K
        # rows per region, comfortably past this; only the small test
        # fixture needs bumping).
        from ecolens.forecasting.repository.training_data import TrainingSetLoader

        rng = np.random.default_rng(9)
        n = 1000
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

        async def fake_fetch(self, regions=None, *, since=None, until=None):
            return df

        monkeypatch.setattr(TrainingSetLoader, "fetch", fake_fetch)

        exit_code = await cli.cmd_feature_selection()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Step 1" in out
        assert "Step 2" in out
        assert "Step 3" in out
        assert "Step 4" in out
        assert "Step 5" in out
