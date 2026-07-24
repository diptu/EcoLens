"""Integration tests for ecolens.forecasting.mlops.{registry,promote,health}
(ECO-115/ECO-116, and root TODO's ECO-T01 "integration test coverage
for ML registry") against a *real* local MLflow tracking store (SQLite
+ local artifact dir under `tmp_path`) -- not a mock. `mlflow.set_tracking_uri`
is process-global, so each test gets its own `tmp_path`-scoped SQLite
file and a unique registered-model name, which is enough isolation
without needing to mock MLflow's client at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import mlflow
import pytest
import torch

from ecolens.config import Settings
from ecolens.forecasting.evaluation.conformal import ConformalCalibration
from ecolens.forecasting.evaluation.evaluate import FullEvaluation, evaluate_model
from ecolens.forecasting.evaluation.metrics import EvaluationReport
from ecolens.forecasting.features import FEATURE_COLUMNS, build_windowed_dataset
from ecolens.forecasting.mlops.health import get_health_snapshot
from ecolens.forecasting.mlops.promote import decide, promote_if_better
from ecolens.forecasting.mlops.registry import ModelRegistry
from ecolens.forecasting.models.lstm import DemandLSTM


@pytest.fixture
def registry(tmp_path, monkeypatch) -> ModelRegistry:
    monkeypatch.chdir(tmp_path)  # keep MLflow's local artifact dirs inside tmp_path
    settings = Settings(  # type: ignore[call-arg]
        mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
        mlflow_experiment_name="test_experiment",
        mlflow_registered_model_name="test_model",
        model_registry_alias="production",
    )
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)
    return ModelRegistry(settings=settings)


def _log_a_run(*, mape: float = 5.0) -> str:
    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
    )
    with mlflow.start_run() as run:
        mlflow.log_metric("test_mape", mape)
        mlflow.pytorch.log_model(model, name="model", serialization_format="pickle")
        return run.info.run_id


class TestModelRegistry:
    def test_register_then_load_by_alias_round_trips_the_model(
        self, registry: ModelRegistry
    ):
        run_id = _log_a_run()
        registered = registry.register(run_id)
        registry.set_alias("production", registered.version)

        loaded = registry.load_by_alias("production")
        assert isinstance(loaded, DemandLSTM)

        x = torch.randn(1, 48, len(FEATURE_COLUMNS))
        outputs, _ = loaded(x)
        assert outputs["p50"].shape == (1, 48)

    def test_get_by_alias_returns_none_when_unset(self, registry: ModelRegistry):
        assert registry.get_by_alias("production") is None

    def test_reassigning_alias_hot_swaps_to_the_new_version(
        self, registry: ModelRegistry
    ):
        run_id_1 = _log_a_run()
        v1 = registry.register(run_id_1)
        registry.set_alias("production", v1.version)
        assert registry.get_by_alias("production").version == v1.version

        run_id_2 = _log_a_run()
        v2 = registry.register(run_id_2)
        registry.set_alias("production", v2.version)

        current = registry.get_by_alias("production")
        assert current.version == v2.version
        assert current.version != v1.version

    def test_list_versions_returns_every_registered_version(
        self, registry: ModelRegistry
    ):
        registry.register(_log_a_run())
        registry.register(_log_a_run())
        versions = registry.list_versions()
        assert len(versions) == 2

    def test_load_by_alias_missing_raises(self, registry: ModelRegistry):
        with pytest.raises(mlflow.exceptions.MlflowException):
            registry.load_by_alias("production")


def _fake_evaluation(mape: float) -> FullEvaluation:
    return FullEvaluation(
        point=EvaluationReport(
            overall={"mae": 0.0, "rmse": 0.0, "mape": mape},
            per_horizon_step=pd.DataFrame(),
            per_region=pd.DataFrame(),
        ),
        conformal=ConformalCalibration(q_hat=np.zeros(48), alpha=0.1),
        test_coverage=0.9,
    )


class TestPromote:
    def test_first_version_always_promotes(self, registry: ModelRegistry):
        v1 = registry.register(_log_a_run())
        decision = decide(registry, v1, _fake_evaluation(10.0), alias="production")
        assert decision.promote is True
        assert decision.current_production_mape is None

    def test_better_challenger_promotes(self, registry: ModelRegistry):
        run_1 = _log_a_run(mape=10.0)
        v1 = registry.register(run_1)
        promote_if_better(registry, v1, _fake_evaluation(10.0), alias="production")

        v2 = registry.register(_log_a_run())
        decision = decide(registry, v2, _fake_evaluation(5.0), alias="production")
        assert decision.promote is True
        assert decision.current_production_mape == 10.0

    def test_worse_challenger_does_not_promote(self, registry: ModelRegistry):
        run_1 = _log_a_run(mape=5.0)
        v1 = registry.register(run_1)
        promote_if_better(registry, v1, _fake_evaluation(5.0), alias="production")

        v2 = registry.register(_log_a_run())
        decision = decide(registry, v2, _fake_evaluation(10.0), alias="production")
        assert decision.promote is False

        # And the alias must genuinely be unchanged in the registry.
        assert registry.get_by_alias("production").version == v1.version

    def test_promote_if_better_actually_mutates_the_registry(
        self, registry: ModelRegistry
    ):
        v1 = registry.register(_log_a_run(mape=10.0))
        promote_if_better(registry, v1, _fake_evaluation(10.0), alias="production")
        assert registry.get_by_alias("production").version == v1.version


class TestHealthSnapshot:
    def test_no_production_model_yet(self, registry: ModelRegistry):
        snapshot = get_health_snapshot(registry, alias="production")
        assert snapshot.has_production_model is False
        assert snapshot.last_trained_at is None

    def test_reports_current_production_version_and_metrics(
        self, registry: ModelRegistry
    ):
        run_id = _log_a_run(mape=7.5)
        v1 = registry.register(run_id)
        registry.set_alias("production", v1.version)

        snapshot = get_health_snapshot(registry, alias="production")
        assert snapshot.has_production_model is True
        assert snapshot.production_version == v1.version
        assert snapshot.last_eval_metrics["test_mape"] == 7.5
        assert snapshot.last_trained_at is not None


class TestEvaluateModelIntegration:
    """One real end-to-end train -> evaluate -> register -> promote,
    exercising every ECO-112..115 module together against the real
    tracking store -- the "does the whole pipeline actually fit
    together" check the individual unit tests can't give.
    """

    def test_full_pipeline(self, registry: ModelRegistry):
        from ecolens.forecasting.training.train import train_model

        rng = np.random.default_rng(42)
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

        dataset = build_windowed_dataset(df, lookback=48, horizon=48)
        result = train_model(
            dataset,
            settings=Settings(  # type: ignore[call-arg]
                model_train_epochs=3,
                model_hidden_size=8,
                model_batch_size=16,
                mlflow_tracking_uri=registry.settings.mlflow_tracking_uri,
            ),
        )
        assert result.run_id

        evaluation = evaluate_model(result.model, dataset, alpha=0.2)
        registered = registry.register(result.run_id)
        decision = promote_if_better(
            registry,
            registered,
            evaluation,
            alias=registry.settings.model_registry_alias,
        )
        assert decision.promote is True

        loaded = registry.load_by_alias(registry.settings.model_registry_alias)
        assert isinstance(loaded, DemandLSTM)
