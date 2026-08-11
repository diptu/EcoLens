"""`service/ml/prune.py`'s structured pruning + fine-tune recovery
pipeline (LSTM-only by design -- see that module's own docstring for why
TFT/TimesFM are explicitly out of scope). Previously had zero automated
coverage despite `compact_lstm`'s own docstring explicitly promising a
`keep_fraction=1.0` no-op check "verified directly in
`tests/test_prune.py`" -- this file is that promise kept, plus real
correctness coverage for the physical compaction math (every affected
tensor: all 4 LSTM gate blocks' rows *and* columns, `attention.score`,
all 3 output heads), the unit-importance ranking that decides *which*
units survive, the benchmark/gate math, and `prune_and_recover`'s own
orchestration logic.

`TestPruneAndRecover` mocks every real DB/MLflow boundary
`prune_and_recover` crosses -- the same boundary `test_training_worker.py`'s
tests mock for the sibling `_and_register_*` orchestration functions
(`load_registered_model`, the DB session, `train_model`,
`evaluate_walk_forward`, `log_and_register_run`, `MlflowClient`) -- so
its assertions are about `prune_and_recover`'s own wiring (does it build
the recovery config from the compacted shape, does it compute the gate
correctly from whatever eval numbers come back, does it tag the
registered version), not about real model accuracy or real wall-clock
latency, which would make the gate assertions flaky/noisy for no real
benefit. `compact_lstm`/`benchmark_models` run for real everywhere else
in this file -- that's the actual mathematically-interesting, bug-prone
part this module exists for."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from app.models.ml import DemandLSTM
from app.service.ml import prune
from app.service.ml.conformal import ConformalCalibration
from app.service.ml.data import _TRAINING_COLUMNS
from app.service.ml.evaluate import EvaluationReport
from app.service.ml.prune import PruneBenchmark, benchmark_models, compact_lstm
from app.service.ml.train import TrainAndRegisterResult, TrainResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _model(
    hidden_size: int = 8, num_layers: int = 1, n_features: int = 5, horizon: int = 3
) -> DemandLSTM:
    torch.manual_seed(0)
    model = DemandLSTM(
        n_features=n_features,
        horizon=horizon,
        hidden_size=hidden_size,
        num_layers=num_layers,
    )
    model.eval()
    return model


def _synthetic_training_rows(n: int, region: str = "NSW1") -> list[dict]:
    """Same shape `test_forecast.py`'s identical helper builds (long-form,
    one row per `(ts, region)`, matching `_TRAINING_COLUMNS`) -- a local
    copy rather than a cross-test-file import, same convention every
    other test file in this suite follows for its own fixtures."""
    ts = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        rows.append(
            dict(
                zip(
                    _TRAINING_COLUMNS,
                    [
                        ts[i],
                        region,
                        5000.0 + 100 * np.sin(i / 10) + rng.normal(0, 5),
                        50.0,
                        5500.0,
                        1500.0,
                        20.0,
                        21.0,
                        50.0,
                        10.0,
                    ],
                    strict=True,
                )
            )
        )
    return rows


class TestCompactLSTM:
    def test_keep_fraction_1_is_an_exact_noop(self):
        model = _model(hidden_size=8, num_layers=1, n_features=5, horizon=3)

        compacted, keep_idx = compact_lstm(model, 1.0)

        assert compacted.lstm.hidden_size == model.lstm.hidden_size
        assert torch.equal(keep_idx, torch.arange(model.lstm.hidden_size))

        x = torch.randn(2, 6, model.n_features)
        with torch.no_grad():
            original_out = model(x)
            compacted_out = compacted(x)
        assert torch.allclose(original_out.p10, compacted_out.p10)
        assert torch.allclose(original_out.p50, compacted_out.p50)
        assert torch.allclose(original_out.p90, compacted_out.p90)

    def test_reduces_hidden_size_and_param_count(self):
        model = _model(hidden_size=8, num_layers=1, n_features=5, horizon=3)

        compacted, keep_idx = compact_lstm(model, 0.5)

        assert compacted.lstm.hidden_size == 4
        assert len(keep_idx) == 4
        assert sum(p.numel() for p in compacted.parameters()) < sum(
            p.numel() for p in model.parameters()
        )

        x = torch.randn(2, 6, model.n_features)
        with torch.no_grad():
            out = compacted(x)
        assert out.p50.shape == (2, model.horizon)
        assert out.p10.shape == out.p90.shape == out.p50.shape

    def test_multi_layer_pruning_stays_shape_consistent_end_to_end(self):
        """Layer 1's input dim is layer 0's (pruned) output -- a shape
        mismatch anywhere in that chain would make `load_state_dict`
        inside `compact_lstm` itself raise before this test ever gets to
        run a forward pass, but a real forward pass through every
        downstream head (`attention`/`point_head`/`*_spread_head`) is the
        honest end-to-end confirmation that all of them were compacted
        consistently, not just the LSTM layers."""
        model = _model(hidden_size=6, num_layers=2, n_features=4, horizon=2)

        compacted, keep_idx = compact_lstm(model, keep_fraction=2 / 3)

        assert compacted.lstm.hidden_size == 4
        assert len(keep_idx) == 4
        x = torch.randn(3, 5, model.n_features)
        with torch.no_grad():
            out = compacted(x)
        assert out.p10.shape == out.p50.shape == out.p90.shape == (3, model.horizon)

    def test_keeps_the_highest_importance_units(self):
        """Real correctness of the unit-importance ranking
        (`_unit_importance`/`_select_units_to_keep`), checked via
        `compact_lstm`'s public `keep_idx` output rather than importing
        those private helpers directly (matching this suite's own
        convention of testing through public entry points). Zeroing one
        unit's entire row *and* column footprint across all 4 gates makes
        it provably the least important unit in the model (importance
        score exactly `0.0`, the real minimum) -- it must be the one
        `compact_lstm` drops."""
        model = _model(hidden_size=4, num_layers=1, n_features=3, horizon=2)
        hidden_size = model.lstm.hidden_size
        zero_unit = 2
        with torch.no_grad():
            model.lstm.weight_hh_l0.fill_(1.0)
            gates = model.lstm.weight_hh_l0.view(4, hidden_size, hidden_size)
            gates[:, zero_unit, :] = 0.0  # this unit's own row, every gate
            gates[:, :, zero_unit] = 0.0  # what this unit feeds into, every gate

        _, keep_idx = compact_lstm(model, keep_fraction=0.75)  # keeps 3 of 4

        assert zero_unit not in keep_idx.tolist()
        assert len(keep_idx) == 3

    @pytest.mark.parametrize("keep_fraction", [0.0, 1.5, -0.1])
    def test_rejects_an_out_of_range_keep_fraction(self, keep_fraction):
        model = _model(hidden_size=4)
        with pytest.raises(ValueError, match="keep_fraction"):
            compact_lstm(model, keep_fraction)


class TestBenchmarkModels:
    def test_reports_a_real_size_and_param_reduction(self):
        model = _model(hidden_size=16, num_layers=1, n_features=6, horizon=4)
        compacted, _ = compact_lstm(model, 0.5)

        benchmark = benchmark_models(model, compacted, lookback=6)

        assert benchmark.pruned_param_count < benchmark.original_param_count
        assert benchmark.pruned_artifact_bytes < benchmark.original_artifact_bytes
        assert benchmark.param_reduction_pct > 0
        assert benchmark.size_reduction_pct > 0
        assert benchmark.original_latency_ms >= 0
        assert benchmark.pruned_latency_ms >= 0


class TestPruneBenchmarkGate:
    """`PruneBenchmark.achieves_a_real_win`'s own gate math -- pure
    dataclass arithmetic, tested directly with hand-picked numbers rather
    than through a real (CPU-timing-noise-prone) benchmark run."""

    def test_passes_with_a_real_size_win_and_no_meaningful_latency_regression(self):
        benchmark = PruneBenchmark(
            original_param_count=1000,
            pruned_param_count=500,
            original_artifact_bytes=1000,
            pruned_artifact_bytes=800,  # 20% smaller
            original_latency_ms=10.0,
            pruned_latency_ms=10.5,  # 5% slower, within the 10% default tolerance
        )
        assert benchmark.achieves_a_real_win() is True

    def test_fails_when_the_size_reduction_is_too_small(self):
        benchmark = PruneBenchmark(
            original_param_count=1000,
            pruned_param_count=980,
            original_artifact_bytes=1000,
            pruned_artifact_bytes=970,  # 3% smaller, below the 5% default minimum
            original_latency_ms=10.0,
            pruned_latency_ms=9.0,
        )
        assert benchmark.achieves_a_real_win() is False

    def test_fails_when_latency_regresses_past_the_tolerance(self):
        benchmark = PruneBenchmark(
            original_param_count=1000,
            pruned_param_count=500,
            original_artifact_bytes=1000,
            pruned_artifact_bytes=800,
            original_latency_ms=10.0,
            pruned_latency_ms=12.0,  # 20% slower, past the 10% default tolerance
        )
        assert benchmark.achieves_a_real_win() is False


class _FakeForecaster:
    def __init__(self, model: DemandLSTM, lookback: int, name: str) -> None:
        self.model = model
        self.lookback = lookback
        self.name = name


class _FakeSessionCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class TestPruneAndRecover:
    @pytest.fixture
    def fake_env(self, monkeypatch):
        original_model = _model(hidden_size=8, num_layers=1, n_features=5, horizon=3)
        forecaster = _FakeForecaster(original_model, lookback=6, name="orig-run")
        raw_df = pd.DataFrame(_synthetic_training_rows(40))

        monkeypatch.setattr(prune, "configure_mlflow", lambda settings: None)
        monkeypatch.setattr(
            prune, "load_registered_model", lambda model_name, version: forecaster
        )
        monkeypatch.setattr(prune, "get_session", lambda: _FakeSessionCtx())

        async def fake_load_training_data(db, regions, since=None):
            return raw_df.copy()

        async def fake_load_holidays(db):
            return pd.DataFrame(columns=["region", "date"])

        monkeypatch.setattr(prune, "load_training_data", fake_load_training_data)
        monkeypatch.setattr(prune, "load_holidays", fake_load_holidays)

        # Deterministic, not a real wall-clock benchmark -- `benchmark_models`
        # (real timing) is covered directly in `TestBenchmarkModels` above;
        # here we're testing `prune_and_recover`'s own gate wiring, which
        # shouldn't depend on CPU-timing noise to be stable.
        fixed_benchmark = PruneBenchmark(
            original_param_count=1000,
            pruned_param_count=500,
            original_artifact_bytes=1000,
            pruned_artifact_bytes=800,
            original_latency_ms=10.0,
            pruned_latency_ms=10.0,
        )
        monkeypatch.setattr(
            prune, "benchmark_models", lambda original, pruned, lookback: fixed_benchmark
        )

        eval_calls: list[str] = []

        def fake_evaluate_walk_forward(candidate, region_df, horizon, *, n_origins, min_history):
            eval_calls.append(candidate.name)
            is_recovered = candidate is not forecaster
            mape = recovered_mape["value"] if is_recovered else 5.0
            return EvaluationReport(
                model_name=candidate.name,
                region="NSW1",
                horizon=horizon,
                n_origins=1,
                mape=mape,
                rmse=1.0,
                pinball_loss_10=1.0,
                pinball_loss_50=1.0,
                pinball_loss_90=1.0,
                empirical_coverage=0.8,
                mean_interval_width=10.0,
                mae=1.0,
                mean_error=0.0,
            )

        recovered_mape = {"value": 5.05}  # close to unpruned's 5.0 -- passes tolerance by default
        monkeypatch.setattr(prune, "evaluate_walk_forward", fake_evaluate_walk_forward)

        calls: dict[str, object] = {}

        def fake_train_model(raw_df, config, *, holidays=None, warm_start_state_dict=None):
            calls["train_config"] = config
            calls["warm_start_state_dict"] = warm_start_state_dict
            recovered_model = DemandLSTM(
                n_features=original_model.n_features,
                horizon=config.horizon,
                hidden_size=config.hidden_size,
                num_layers=config.num_layers,
            )
            recovered_model.eval()
            return TrainResult(
                model=recovered_model,
                calibration=ConformalCalibration(q=np.full(config.horizon, 10.0), alpha=0.2),
                feature_scalers={},
                target_scaler=object(),
                test_metrics={"test_mape": 4.2},
            )

        monkeypatch.setattr(prune, "train_model", fake_train_model)

        def fake_log_and_register_run(
            result, config, regions, model_name, *, register, extra_tags=None, extra_params=None
        ):
            calls["log_register_extra_params"] = extra_params
            calls["log_register_extra_tags"] = extra_tags
            calls["log_register_register"] = register
            return TrainAndRegisterResult(
                run_id="recovered-run-1",
                model_version="7" if register else None,
                test_metrics=result.test_metrics,
                final_val_mape=None,
            )

        monkeypatch.setattr(prune, "log_and_register_run", fake_log_and_register_run)

        class _FakeMlflowClient:
            def __init__(self) -> None:
                self.tags: dict[tuple[str, str, str], str] = {}

            def set_model_version_tag(self, model_name, version, key, value):
                self.tags[(model_name, version, key)] = value

        fake_client = _FakeMlflowClient()
        monkeypatch.setattr(prune, "MlflowClient", lambda: fake_client)

        return {
            "forecaster": forecaster,
            "original_model": original_model,
            "raw_df": raw_df,
            "recovered_mape": recovered_mape,
            "eval_calls": eval_calls,
            "calls": calls,
            "client": fake_client,
        }

    async def test_builds_the_recovery_config_from_the_compacted_shape(self, fake_env):
        result = await prune.prune_and_recover(
            "lstm_demand", "3", ["NSW1"], 0.5, recovery_epochs=1, n_origins=1
        )

        config = fake_env["calls"]["train_config"]
        assert config.hidden_size == 4  # 8 * 0.5
        assert config.num_layers == 1
        assert config.horizon == fake_env["original_model"].horizon
        assert config.epochs == 1
        assert fake_env["calls"]["warm_start_state_dict"] is not None
        assert result.recovered_test_mape == 4.2

    async def test_passes_the_gate_and_registers_when_recovery_holds_up(self, fake_env):
        result = await prune.prune_and_recover(
            "lstm_demand", "3", ["NSW1"], 0.5, recovery_epochs=1, n_origins=1
        )

        assert fake_env["eval_calls"] == ["orig-run", "lstm_demand_pruned_candidate"]
        assert result.unpruned_eval_mape == pytest.approx(5.0)
        assert result.recovered_eval_mape == pytest.approx(5.05)
        assert result.relative_mape_regression_pct == pytest.approx(1.0, abs=0.01)
        assert result.passes_accuracy_tolerance is True
        assert result.achieves_size_latency_win is True  # `fixed_benchmark` above is a real win
        assert result.gate_passed is True
        assert result.recovered_model_version == "7"

        assert fake_env["client"].tags[("lstm_demand", "7", "prune_gate_passed")] == "True"
        extra_params = fake_env["calls"]["log_register_extra_params"]
        assert extra_params["keep_fraction"] == 0.5
        assert extra_params["n_units_kept"] == 4
        assert extra_params["prune_gate_passed"] is True
        assert fake_env["calls"]["log_register_extra_tags"]["training_type"] == "pruned_recovery"

    async def test_fails_the_gate_but_still_registers_when_recovery_regresses_too_much(
        self, fake_env
    ):
        """`prune_and_recover`'s own docstring: `register=True` always
        registers for auditability even when the gate fails -- "the
        honest result is 'pruning wasn't worth it', which is a legitimate
        real outcome to report, not a failure to hide." A version that
        can't recover its accuracy must still show up in the registry,
        tagged `prune_gate_passed=False`, not silently vanish."""
        fake_env["recovered_mape"]["value"] = 9.0  # 80% worse than unpruned's 5.0

        result = await prune.prune_and_recover(
            "lstm_demand", "3", ["NSW1"], 0.5, recovery_epochs=1, n_origins=1
        )

        assert result.passes_accuracy_tolerance is False
        assert result.gate_passed is False
        # Still registered -- the gate failing doesn't stop registration,
        # only what gets tagged onto the version it produced.
        assert result.recovered_model_version == "7"
        assert fake_env["client"].tags[("lstm_demand", "7", "prune_gate_passed")] == "False"

    async def test_raises_when_no_training_data_is_available(self, fake_env, monkeypatch):
        async def empty_load_training_data(db, regions, since=None):
            return pd.DataFrame(columns=_TRAINING_COLUMNS)

        monkeypatch.setattr(prune, "load_training_data", empty_load_training_data)

        with pytest.raises(ValueError, match="no data found"):
            await prune.prune_and_recover(
                "lstm_demand", "3", ["NSW1"], 0.5, recovery_epochs=1, n_origins=1
            )
