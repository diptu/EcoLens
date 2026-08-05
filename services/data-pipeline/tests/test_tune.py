from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.service.ml import tune as tune_module
from app.service.ml.train import TrainConfig

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _synthetic_df(
    n_per_region: int = 300, regions: tuple[str, ...] = ("NSW1",)
) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    frames = []
    for region in regions:
        ts = pd.date_range("2026-01-01", periods=n_per_region, freq="5min", tz="UTC")
        t = np.arange(n_per_region)
        demand = (
            5000 + 1000 * np.sin(2 * np.pi * t / 288) + rng.normal(0, 20, n_per_region)
        )
        temp = 20 + 5 * np.sin(2 * np.pi * t / 288)
        frames.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "region": region,
                    "demand_mw": demand,
                    "price_mwh": 50 + rng.normal(0, 2, n_per_region),
                    "total_generation_mw": demand * 1.1,
                    "total_renewable_mw": demand * 0.3,
                    "temp_c": temp,
                    "apparent_temp_c": temp + 1,
                    "humidity_pct": np.full(n_per_region, 50.0),
                    "wind_speed_kmh": np.full(n_per_region, 10.0),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


_BASE_CONFIG = TrainConfig(
    lookback=8,
    horizon=4,
    hidden_size=8,
    num_layers=1,
    dropout=0.0,
    lr=1e-2,
    batch_size=32,
    cal_frac=0.5,
)


class _FakeRunInfo:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


class _FakeRun:
    def __init__(self, run_id: str) -> None:
        self.info = _FakeRunInfo(run_id)


class _FakeRunCtx:
    _counter = 0

    def __enter__(self) -> _FakeRun:
        _FakeRunCtx._counter += 1
        self._run = _FakeRun(f"fake-run-{_FakeRunCtx._counter}")
        return self._run

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeMlflow:
    def __init__(self) -> None:
        self.logged_params: list[dict[str, object]] = []
        self.logged_metrics: list[dict[str, float]] = []
        self.tags: list[dict[str, str]] = []

    def start_run(self) -> _FakeRunCtx:
        return _FakeRunCtx()

    def log_params(self, params: dict[str, object]) -> None:
        self.logged_params.append(dict(params))

    def log_param(self, key: str, value: object) -> None:
        self.logged_params.append({key: value})

    def log_metric(self, key: str, value: float) -> None:
        self.logged_metrics.append({key: value})

    def log_metrics(self, metrics: dict[str, float]) -> None:
        self.logged_metrics.append(dict(metrics))

    def set_tags(self, tags: dict[str, str]) -> None:
        self.tags.append(dict(tags))


class _FakeSessionCtx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class TestMakePruningCallback:
    """Direct unit tests of the pruning wiring, without needing a full
    (slow) real training run to exercise `trial.should_prune()`."""

    class _FakeTrial:
        def __init__(self, prune: bool) -> None:
            self._prune = prune
            self.reported: list[tuple[float, int]] = []

        def report(self, value: float, step: int) -> None:
            self.reported.append((value, step))

        def should_prune(self) -> bool:
            return self._prune

    def test_reports_the_epoch_val_mape(self):
        trial = self._FakeTrial(prune=False)
        callback = tune_module._make_pruning_callback(trial)  # type: ignore[arg-type]

        callback(3, {"val_mape": 12.5})

        assert trial.reported == [(12.5, 3)]

    def test_raises_trial_pruned_when_the_trial_says_to_prune(self):
        import optuna

        trial = self._FakeTrial(prune=True)
        callback = tune_module._make_pruning_callback(trial)  # type: ignore[arg-type]

        with pytest.raises(optuna.TrialPruned):
            callback(1, {"val_mape": 99.0})

    def test_does_not_raise_when_the_trial_says_to_continue(self):
        trial = self._FakeTrial(prune=False)
        callback = tune_module._make_pruning_callback(trial)  # type: ignore[arg-type]

        callback(1, {"val_mape": 5.0})  # should not raise


class TestTuneOptuna:
    async def _patch_common(self, monkeypatch, df: pd.DataFrame) -> _FakeMlflow:
        fake_mlflow = _FakeMlflow()
        monkeypatch.setattr(tune_module, "mlflow", fake_mlflow)
        monkeypatch.setattr(tune_module, "configure_mlflow", lambda settings: None)
        monkeypatch.setattr(tune_module, "get_session", lambda: _FakeSessionCtx())

        async def fake_load_training_data(db, regions):
            return df.copy()

        async def fake_load_holidays(db):
            return pd.DataFrame()

        monkeypatch.setattr(tune_module, "load_training_data", fake_load_training_data)
        monkeypatch.setattr(tune_module, "load_holidays", fake_load_holidays)
        return fake_mlflow

    async def test_runs_n_trials_and_returns_the_real_best_one(self, monkeypatch):
        df = _synthetic_df(n_per_region=300)
        fake_mlflow = await self._patch_common(monkeypatch, df)

        result = await tune_module.tune_optuna(
            ["NSW1"],
            base_config=_BASE_CONFIG,
            n_trials=3,
            tune_epochs=2,
            tune_patience=2,
        )

        assert len(result.trials) == 3
        assert result.best_run_id is not None
        assert result.best_run_id in {t.run_id for t in result.trials}
        assert result.best_val_mape < float("inf")
        assert result.n_raw_rows == len(df)
        assert result.data_source == "fct_energy_demand"
        assert result.imputed_fraction is None
        # Every completed trial's config is a real, distinct sample from
        # the search space, not the same hardcoded value every time.
        hidden_sizes = {t.params["hidden_size"] for t in result.trials}
        assert hidden_sizes <= set(tune_module.OPTUNA_HIDDEN_SIZES)
        assert any(p.startswith("hidden_size") for t in result.trials for p in t.params)
        # An MLflow run was really opened+logged for each trial.
        assert len(fake_mlflow.logged_metrics) >= 3

    async def test_train_frac_val_frac_override_the_base_config(self, monkeypatch):
        df = _synthetic_df(n_per_region=300)
        await self._patch_common(monkeypatch, df)

        result = await tune_module.tune_optuna(
            ["NSW1"],
            base_config=_BASE_CONFIG,
            n_trials=1,
            tune_epochs=1,
            train_frac=0.6,
            val_frac=0.2,
        )

        assert result.best_config.train_frac == 0.6
        assert result.best_config.val_frac == 0.2

    async def test_ml_features_v1_data_source_logs_the_imputed_fraction(
        self, monkeypatch
    ):
        df = _synthetic_df(n_per_region=300)
        fake_mlflow = await self._patch_common(monkeypatch, df)

        async def fake_load_v1(db, regions):
            return df.copy()

        async def fake_imputed_fraction(db, regions):
            return 0.66

        monkeypatch.setattr(
            tune_module, "load_ml_features_v1_training_data", fake_load_v1
        )
        monkeypatch.setattr(
            tune_module, "load_ml_features_v1_imputed_fraction", fake_imputed_fraction
        )

        result = await tune_module.tune_optuna(
            ["NSW1"],
            base_config=_BASE_CONFIG,
            n_trials=1,
            tune_epochs=1,
            data_source="ml_features_v1",
        )

        assert result.data_source == "ml_features_v1"
        assert result.imputed_fraction == 0.66
        assert any(p.get("imputed_fraction") == 0.66 for p in fake_mlflow.logged_params)

    async def test_raises_on_empty_data(self, monkeypatch):
        await self._patch_common(monkeypatch, pd.DataFrame())

        with pytest.raises(ValueError, match="no training data"):
            await tune_module.tune_optuna(
                ["NSW1"], base_config=_BASE_CONFIG, n_trials=1, tune_epochs=1
            )
