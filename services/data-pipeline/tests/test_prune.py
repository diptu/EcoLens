from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch
from sklearn.preprocessing import StandardScaler

from app.models.ml import DemandLSTM
from app.service.ml.conformal import ConformalCalibration
from app.service.ml.prune import (
    PruneBenchmark,
    _select_units_to_keep,
    _unit_importance,
    benchmark_models,
    compact_lstm,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestUnitImportance:
    def test_returns_one_score_per_hidden_unit(self):
        hidden_size = 6
        weight_hh = torch.randn(4 * hidden_size, hidden_size)

        scores = _unit_importance(weight_hh, hidden_size)

        assert scores.shape == (hidden_size,)

    def test_a_zeroed_unit_scores_lower_than_a_normal_one(self):
        hidden_size = 6
        weight_hh = torch.randn(4 * hidden_size, hidden_size)
        # Zero unit 2's row across all 4 gates AND its column across all
        # 4 gates -- a real "this unit contributes nothing" state.
        gates = weight_hh.reshape(4, hidden_size, hidden_size)
        gates[:, 2, :] = 0.0
        gates[:, :, 2] = 0.0
        weight_hh = gates.reshape(4 * hidden_size, hidden_size)

        scores = _unit_importance(weight_hh, hidden_size)

        assert scores[2] == pytest.approx(0.0)
        assert (scores[torch.tensor([0, 1, 3, 4, 5])] > 0).all()


class TestSelectUnitsToKeep:
    def test_keep_fraction_1_keeps_every_unit(self):
        hidden_size = 8
        state_dict = {"lstm.weight_hh_l0": torch.randn(4 * hidden_size, hidden_size)}

        keep_idx = _select_units_to_keep(state_dict, hidden_size, 1.0)

        assert sorted(keep_idx.tolist()) == list(range(hidden_size))

    def test_keep_fraction_half_keeps_half(self):
        hidden_size = 8
        state_dict = {"lstm.weight_hh_l0": torch.randn(4 * hidden_size, hidden_size)}

        keep_idx = _select_units_to_keep(state_dict, hidden_size, 0.5)

        assert len(keep_idx) == 4

    def test_keeps_the_real_highest_importance_units(self):
        hidden_size = 4
        gates = torch.zeros(4, hidden_size, hidden_size)
        # Make unit 0 and unit 3 obviously important, 1 and 2 obviously not.
        gates[:, 0, :] = 10.0
        gates[:, 3, :] = 10.0
        gates[:, 1, :] = 0.01
        gates[:, 2, :] = 0.01
        state_dict = {"lstm.weight_hh_l0": gates.reshape(4 * hidden_size, hidden_size)}

        keep_idx = _select_units_to_keep(state_dict, hidden_size, 0.5)

        assert sorted(keep_idx.tolist()) == [0, 3]

    def test_rejects_out_of_range_keep_fraction(self):
        state_dict = {"lstm.weight_hh_l0": torch.randn(4, 1)}

        with pytest.raises(ValueError, match="keep_fraction"):
            _select_units_to_keep(state_dict, 1, 0.0)

        with pytest.raises(ValueError, match="keep_fraction"):
            _select_units_to_keep(state_dict, 1, 1.5)


class TestCompactLstm:
    def _model(self, **kwargs):
        defaults = dict(n_features=5, horizon=3, hidden_size=8, num_layers=1)
        defaults.update(kwargs)
        return DemandLSTM(**defaults)

    def test_keep_fraction_1_is_an_exact_no_op(self):
        torch.manual_seed(0)
        model = self._model()
        model.eval()
        x = torch.randn(2, 6, 5)
        original_out = model(x)

        compacted, keep_idx = compact_lstm(model, keep_fraction=1.0)
        compacted.eval()
        compacted_out = compacted(x)

        assert compacted.lstm.hidden_size == model.lstm.hidden_size
        assert sorted(keep_idx.tolist()) == list(range(model.lstm.hidden_size))
        assert torch.allclose(original_out.p50, compacted_out.p50, atol=1e-5)
        assert torch.allclose(original_out.p10, compacted_out.p10, atol=1e-5)
        assert torch.allclose(original_out.p90, compacted_out.p90, atol=1e-5)

    def test_reduces_hidden_size_by_the_real_kept_count(self):
        model = self._model(hidden_size=8)

        compacted, keep_idx = compact_lstm(model, keep_fraction=0.5)

        assert compacted.lstm.hidden_size == 4
        assert len(keep_idx) == 4

    def test_reduces_real_parameter_count(self):
        model = self._model(hidden_size=16)

        compacted, _ = compact_lstm(model, keep_fraction=0.5)

        original_params = sum(p.numel() for p in model.parameters())
        compacted_params = sum(p.numel() for p in compacted.parameters())
        assert compacted_params < original_params

    def test_produces_finite_outputs_after_real_pruning(self):
        torch.manual_seed(0)
        model = self._model(hidden_size=16)
        compacted, _ = compact_lstm(model, keep_fraction=0.5)
        compacted.eval()
        x = torch.randn(2, 6, 5)

        out = compacted(x)

        assert torch.isfinite(out.p50).all()
        assert torch.isfinite(out.p10).all()
        assert torch.isfinite(out.p90).all()
        assert (out.p10 <= out.p50).all()
        assert (out.p50 <= out.p90).all()

    def test_works_with_multiple_lstm_layers(self):
        torch.manual_seed(0)
        model = self._model(hidden_size=8, num_layers=2)
        model.eval()
        x = torch.randn(2, 6, 5)

        compacted, keep_idx = compact_lstm(model, keep_fraction=0.5)
        compacted.eval()
        out = compacted(x)

        assert compacted.lstm.num_layers == 2
        assert compacted.lstm.hidden_size == 4
        assert torch.isfinite(out.p50).all()

        # Also confirm the exact-no-op invariant holds with num_layers=2.
        no_op, _ = compact_lstm(model, keep_fraction=1.0)
        no_op.eval()
        no_op_out = no_op(x)
        original_out = model(x)
        assert torch.allclose(original_out.p50, no_op_out.p50, atol=1e-5)


class TestBenchmarkModels:
    def test_produces_a_real_comparative_report(self):
        torch.manual_seed(0)
        model = DemandLSTM(n_features=5, horizon=3, hidden_size=16, num_layers=1)
        compacted, _ = compact_lstm(model, keep_fraction=0.5)

        report = benchmark_models(model, compacted, lookback=6)

        assert report.pruned_param_count < report.original_param_count
        assert report.param_reduction_pct > 0
        assert report.pruned_artifact_bytes < report.original_artifact_bytes
        assert report.size_reduction_pct > 0
        assert report.original_latency_ms > 0
        assert report.pruned_latency_ms > 0


class TestPruneBenchmarkAchievesARealWin:
    def _report(self, *, size_reduction_pct, latency_change_pct):
        # Construct a report whose computed properties yield the given
        # percentages exactly, so the win/no-win logic is tested against
        # known, hand-picked numbers rather than real model noise.
        original_bytes = 1000
        pruned_bytes = round(original_bytes * (1 - size_reduction_pct / 100))
        original_latency = 10.0
        pruned_latency = original_latency * (1 + latency_change_pct / 100)
        return PruneBenchmark(
            original_param_count=100,
            pruned_param_count=50,
            original_artifact_bytes=original_bytes,
            pruned_artifact_bytes=pruned_bytes,
            original_latency_ms=original_latency,
            pruned_latency_ms=pruned_latency,
        )

    def test_wins_when_smaller_and_not_slower(self):
        report = self._report(size_reduction_pct=20, latency_change_pct=0)

        assert report.achieves_a_real_win() is True

    def test_does_not_win_when_size_reduction_is_too_small(self):
        report = self._report(size_reduction_pct=1, latency_change_pct=0)

        assert report.achieves_a_real_win() is False

    def test_does_not_win_when_meaningfully_slower(self):
        report = self._report(size_reduction_pct=20, latency_change_pct=50)

        assert report.achieves_a_real_win() is False

    def test_wins_when_smaller_and_slightly_slower_within_tolerance(self):
        report = self._report(size_reduction_pct=20, latency_change_pct=5)

        assert report.achieves_a_real_win() is True


class TestPruneAndRecover:
    """Real, mostly-unmocked integration test: only the DB query and
    MLflow registry calls are faked (external I/O this test can't do
    for real); `compact_lstm`, `benchmark_models`, real `train_model`
    (recovery fine-tune), and `evaluate_walk_forward` all run for real
    against small synthetic data, matching `test_train.py`'s
    `_synthetic_demand_df` pattern."""

    def _synthetic_df(self, n: int = 400) -> pd.DataFrame:
        rng = np.random.default_rng(7)
        ts = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
        t = np.arange(n)
        demand = 5000 + 1000 * np.sin(2 * np.pi * t / 288) + rng.normal(0, 20, n)
        temp = 20 + 5 * np.sin(2 * np.pi * t / 288)
        return pd.DataFrame(
            {
                "ts": ts,
                "region": "NSW1",
                "demand_mw": demand,
                "price_mwh": 50 + rng.normal(0, 2, n),
                "total_generation_mw": demand * 1.1,
                "total_renewable_mw": demand * 0.3,
                "temp_c": temp,
                "apparent_temp_c": temp + 1,
                "humidity_pct": np.full(n, 50.0),
                "wind_speed_kmh": np.full(n, 10.0),
            }
        )

    async def test_full_pipeline_runs_and_reports_a_real_gate_decision(
        self, monkeypatch
    ):
        from app.service.ml import prune as prune_module
        from app.service.ml.evaluate import LSTMForecaster
        from app.service.ml.features import (
            FEATURE_COLUMNS,
            NUMERIC_COLUMNS,
            TARGET_COLUMN,
            build_features,
        )
        from app.service.ml.train import TrainAndRegisterResult

        raw_df = self._synthetic_df(n=400)
        engineered = build_features(raw_df)

        original_model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), horizon=4, hidden_size=16, num_layers=1
        )
        feature_scaler = StandardScaler().fit(
            engineered[list(NUMERIC_COLUMNS)].dropna().to_numpy()
        )
        target_scaler = StandardScaler().fit(
            engineered[[TARGET_COLUMN]].dropna().to_numpy()
        )
        forecaster = LSTMForecaster(
            model=original_model,
            feature_scalers={"NSW1": feature_scaler},
            target_scaler=target_scaler,
            lookback=8,
            calibration=ConformalCalibration(q=np.full(4, 10.0), alpha=0.2),
            name="lstm_demand_v1",
        )

        monkeypatch.setattr(
            prune_module, "load_registered_model", lambda name, version: forecaster
        )

        class _FakeSessionCtx:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(prune_module, "get_session", lambda: _FakeSessionCtx())

        async def fake_load_training_data(db, regions):
            return raw_df.copy()

        async def fake_load_holidays(db):
            return pd.DataFrame()

        monkeypatch.setattr(prune_module, "load_training_data", fake_load_training_data)
        monkeypatch.setattr(prune_module, "load_holidays", fake_load_holidays)

        captured = {}

        def fake_log_and_register_run(
            result,
            config,
            regions,
            model_name,
            *,
            register,
            extra_tags=None,
            extra_params=None,
        ):
            captured["extra_tags"] = extra_tags
            captured["extra_params"] = extra_params
            return TrainAndRegisterResult(
                run_id="run-pruned-1",
                model_version="9" if register else None,
                test_metrics=result.test_metrics,
                final_val_mape=None,
            )

        monkeypatch.setattr(
            prune_module, "log_and_register_run", fake_log_and_register_run
        )

        class _FakeMlflowClient:
            def __init__(self):
                self.tags = {}

            def set_model_version_tag(self, model_name, version, key, value):
                self.tags[(model_name, version, key)] = value

        fake_client = _FakeMlflowClient()
        monkeypatch.setattr(prune_module, "MlflowClient", lambda: fake_client)
        monkeypatch.setattr(prune_module, "configure_mlflow", lambda settings: None)

        # Tiny epochs so the real recovery fine-tune runs fast in a test.
        result = await prune_module.prune_and_recover(
            "lstm_demand",
            1,
            ["NSW1"],
            keep_fraction=0.5,
            recovery_epochs=2,
            n_origins=3,
        )

        assert result.recovered_run_id == "run-pruned-1"
        assert (
            result.benchmark.pruned_param_count < result.benchmark.original_param_count
        )
        assert isinstance(result.gate_passed, bool)
        assert captured["extra_tags"]["training_type"] == "pruned_recovery"
        assert captured["extra_params"]["keep_fraction"] == 0.5
        assert "prune_gate_passed" in captured["extra_params"]
        if result.recovered_model_version:
            assert fake_client.tags[("lstm_demand", "9", "prune_gate_passed")] == str(
                result.gate_passed
            )
