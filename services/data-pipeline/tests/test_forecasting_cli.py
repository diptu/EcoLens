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
from ecolens.forecasting import cli
from ecolens.forecasting.features import FEATURE_COLUMNS, build_windowed_dataset


def _dataset():
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
    return build_windowed_dataset(df, lookback=48, horizon=48)


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

    async def fake_fetch_and_window(settings: Settings):
        return dataset

    monkeypatch.setattr(cli, "_fetch_and_window", fake_fetch_and_window)
    yield
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


class TestCmdTrain:
    @pytest.mark.asyncio
    async def test_trains_registers_and_promotes(self, cli_env, capsys):
        exit_code = await cli.cmd_train()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "trained version" in out
        assert "promoted=True" in out


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


class TestCmdTune:
    @pytest.mark.asyncio
    async def test_runs_a_small_study(self, cli_env, capsys):
        exit_code = await cli.cmd_tune(2)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "best params" in out
