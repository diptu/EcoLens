import json

import pytest
from click.testing import CliRunner

from app import cli
from app.service import auth as auth_service
from app.service.ml import evaluate as ml_evaluate
from app.service.ml import train as ml_train
from app.service.ml import train_tft as ml_train_tft
from app.service.ml import tune as ml_tune
from app.service.pipeline.tasks import registry


@pytest.fixture
def runner():
    return CliRunner()


def test_help_lists_all_subcommand_groups(runner):
    result = runner.invoke(cli.main, ["--help"])

    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "dbt" in result.output
    assert "worker" in result.output
    assert "train-worker" in result.output
    assert "serve" in result.output
    assert "health" in result.output


def test_health_prints_the_same_shape_as_the_api_endpoint(runner):
    result = runner.invoke(cli.main, ["health"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "ok"}


def test_version_flag(runner):
    result = runner.invoke(cli.main, ["--version"])

    assert result.exit_code == 0
    assert "ecolens-pipeline" in result.output


class TestIngestSubcommands:
    def test_bom_success_reports_rows_staged(self, runner, monkeypatch):
        async def fake_run_source(key, **kwargs):
            assert key == "bom"
            assert kwargs == {"triggered_by": "manual", "lookback_minutes": 45}
            return 288

        monkeypatch.setattr(cli, "run_source", fake_run_source)

        result = runner.invoke(cli.main, ["ingest", "bom", "--lookback-minutes", "45"])

        assert result.exit_code == 0
        assert "bom: 288 rows staged" in result.output

    def test_bom_omits_lookback_minutes_when_not_given(self, runner, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["kwargs"] = kwargs
            return 0

        monkeypatch.setattr(cli, "run_source", fake_run_source)

        runner.invoke(cli.main, ["ingest", "bom"])

        assert captured["kwargs"] == {"triggered_by": "manual"}

    def test_holidays_uses_year_not_lookback_minutes(self, runner, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["key"] = key
            captured["kwargs"] = kwargs
            return 42

        monkeypatch.setattr(cli, "run_source", fake_run_source)

        result = runner.invoke(cli.main, ["ingest", "holidays", "--year", "2030"])

        assert result.exit_code == 0
        assert captured == {
            "key": "holidays",
            "kwargs": {"triggered_by": "manual", "year": 2030},
        }

    def test_default_triggered_by_is_manual_and_skips_pause_check(
        self, runner, monkeypatch
    ):
        """Pause is only enforced for `--triggered-by schedule` -- a bare
        manual invocation should never even query `meta.pipelines`."""

        async def fake_is_paused(db, key):
            raise AssertionError("manual runs must not check pause state")

        async def fake_run_source(key, **kwargs):
            return 1

        monkeypatch.setattr(cli, "is_pipeline_paused", fake_is_paused)
        monkeypatch.setattr(cli, "run_source", fake_run_source)

        result = runner.invoke(cli.main, ["ingest", "bom"])

        assert result.exit_code == 0

    def test_schedule_triggered_run_checks_pause_and_proceeds_when_active(
        self, runner, monkeypatch
    ):
        captured = {}

        async def fake_is_paused(db, key):
            captured["checked_key"] = key
            return False

        async def fake_run_source(key, **kwargs):
            captured["kwargs"] = kwargs
            return 5

        monkeypatch.setattr(cli, "is_pipeline_paused", fake_is_paused)
        monkeypatch.setattr(cli, "run_source", fake_run_source)

        result = runner.invoke(
            cli.main, ["ingest", "bom", "--triggered-by", "schedule"]
        )

        assert result.exit_code == 0
        assert captured["checked_key"] == "bom"
        assert captured["kwargs"]["triggered_by"] == "schedule"
        assert "bom: 5 rows staged" in result.output

    def test_schedule_triggered_run_skips_when_paused(self, runner, monkeypatch):
        async def fake_is_paused(db, key):
            return True

        async def fake_run_source(key, **kwargs):
            raise AssertionError("run_source must not be called for a paused pipeline")

        monkeypatch.setattr(cli, "is_pipeline_paused", fake_is_paused)
        monkeypatch.setattr(cli, "run_source", fake_run_source)

        result = runner.invoke(
            cli.main, ["ingest", "bom", "--triggered-by", "schedule"]
        )

        assert result.exit_code == 0
        assert "bom: skipped — pipeline is paused" in result.output

    def test_all_5_sources_have_a_subcommand(self, runner):
        result = runner.invoke(cli.main, ["ingest", "--help"])

        for key in registry.SOURCES:
            assert key in result.output

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_run_source(key, **kwargs):
            raise RuntimeError("upstream is down")

        monkeypatch.setattr(cli, "run_source", fake_run_source)

        result = runner.invoke(cli.main, ["ingest", "aemo-nem"])

        assert result.exit_code == 1
        assert "upstream is down" in result.output


class TestDbtSubcommands:
    def test_build_success(self, runner, monkeypatch):
        monkeypatch.setattr(cli, "run_dbt", lambda *a, **k: 0)

        result = runner.invoke(cli.main, ["dbt", "build"])

        assert result.exit_code == 0
        assert "dbt build: succeeded" in result.output

    def test_test_failure_exits_with_dbts_own_code(self, runner, monkeypatch):
        monkeypatch.setattr(cli, "run_dbt", lambda *a, **k: 1)

        result = runner.invoke(cli.main, ["dbt", "test"])

        assert result.exit_code == 1
        assert "failed" in result.output

    def test_extra_args_and_target_are_forwarded(self, runner, monkeypatch):
        captured = {}

        def fake_run_dbt(subcommand, project_dir, target, extra_args):
            captured["subcommand"] = subcommand
            captured["target"] = target
            captured["extra_args"] = extra_args
            return 0

        monkeypatch.setattr(cli, "run_dbt", fake_run_dbt)

        # `--` is required so Click treats --select as a positional
        # extra_arg rather than trying to parse it as its own option.
        result = runner.invoke(
            cli.main,
            ["dbt", "run", "--target", "dev", "--", "--select", "stg_aemo_nem"],
        )

        assert result.exit_code == 0, result.output
        assert captured["subcommand"] == "run"
        assert captured["target"] == "dev"
        assert captured["extra_args"] == ["--select", "stg_aemo_nem"]


class TestTrainCommand:
    def test_success_reports_run_and_registration(self, runner, monkeypatch):
        async def fake_train_and_register(model_name, regions, **kwargs):
            return ml_train.TrainAndRegisterResult(
                run_id="run-abc123",
                model_version="7",
                test_metrics={"test_mape": 4.5, "test_coverage_calibrated": 0.81},
                final_val_mape=4.2,
            )

        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["train"])

        assert result.exit_code == 0, result.output
        assert "run-abc123" in result.output
        assert "registered as" in result.output
        assert "v7" in result.output
        assert "test_mape=4.50" in result.output

    def test_no_register_flag_is_reported(self, runner, monkeypatch):
        async def fake_train_and_register(model_name, regions, **kwargs):
            assert kwargs["register"] is False
            return ml_train.TrainAndRegisterResult(
                run_id="run-xyz",
                model_version=None,
                test_metrics={},
                final_val_mape=None,
            )

        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["train", "--no-register"])

        assert result.exit_code == 0, result.output
        assert "not registered" in result.output

    def test_region_option_is_forwarded(self, runner, monkeypatch):
        captured = {}

        async def fake_train_and_register(model_name, regions, **kwargs):
            captured["regions"] = list(regions)
            return ml_train.TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(
            cli.main, ["train", "--region", "QLD1", "--region", "SA1"]
        )

        assert result.exit_code == 0, result.output
        assert captured["regions"] == ["QLD1", "SA1"]

    def test_since_option_is_parsed_and_forwarded(self, runner, monkeypatch):
        """`--since` (`todo-model-training.md`'s OE region-join blocker
        follow-up, 2026-08-05) -- without it, a real run against the full
        AEMO history starves train/val/calibration of real data whenever
        the newest feature (`total_generation_mw`) only covers a recent
        window (confirmed live: 20/5/0 rows against 27,328 real usable
        rows). CLI must parse the ISO date into a UTC-aware
        `pd.Timestamp` before forwarding it."""
        import pandas as pd

        captured = {}

        async def fake_train_and_register(model_name, regions, **kwargs):
            captured["since"] = kwargs["since"]
            return ml_train.TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["train", "--since", "2026-07-15"])

        assert result.exit_code == 0, result.output
        assert captured["since"] == pd.Timestamp("2026-07-15", tz="UTC")

    def test_since_option_defaults_to_none(self, runner, monkeypatch):
        captured = {}

        async def fake_train_and_register(model_name, regions, **kwargs):
            captured["since"] = kwargs["since"]
            return ml_train.TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["train"])

        assert result.exit_code == 0, result.output
        assert captured["since"] is None

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_train_and_register(model_name, regions, **kwargs):
            raise ValueError("no training data found in the warehouse")

        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["train"])

        assert result.exit_code == 1
        assert "no training data found" in result.output


class TestTrainTftCommand:
    def test_success_reports_run_and_registration(self, runner, monkeypatch):
        async def fake_train_and_register_tft(model_name, regions, **kwargs):
            return ml_train.TrainAndRegisterResult(
                run_id="run-tft-1",
                model_version="1",
                test_metrics={"test_mape": 6.5, "test_coverage_calibrated": 0.79},
                final_val_mape=6.1,
            )

        monkeypatch.setattr(
            ml_train_tft, "train_and_register_tft", fake_train_and_register_tft
        )

        result = runner.invoke(cli.main, ["train-tft"])

        assert result.exit_code == 0, result.output
        assert "run-tft-1" in result.output
        assert "registered as" in result.output
        assert "v1" in result.output
        assert "test_mape=6.50" in result.output

    def test_defaults_model_name_to_lstm_demand_tft_not_lstm_demand(
        self, runner, monkeypatch
    ):
        captured = {}

        async def fake_train_and_register_tft(model_name, regions, **kwargs):
            captured["model_name"] = model_name
            return ml_train.TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            ml_train_tft, "train_and_register_tft", fake_train_and_register_tft
        )

        result = runner.invoke(cli.main, ["train-tft"])

        assert result.exit_code == 0, result.output
        assert captured["model_name"] == "lstm_demand_tft"

    def test_region_and_model_name_options_are_forwarded(self, runner, monkeypatch):
        captured = {}

        async def fake_train_and_register_tft(model_name, regions, **kwargs):
            captured["model_name"] = model_name
            captured["regions"] = list(regions)
            return ml_train.TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            ml_train_tft, "train_and_register_tft", fake_train_and_register_tft
        )

        result = runner.invoke(
            cli.main,
            [
                "train-tft",
                "--region",
                "QLD1",
                "--region",
                "SA1",
                "--model-name",
                "lstm_demand_tft_v2",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["regions"] == ["QLD1", "SA1"]
        assert captured["model_name"] == "lstm_demand_tft_v2"

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_train_and_register_tft(model_name, regions, **kwargs):
            raise ValueError("no training data found in the warehouse")

        monkeypatch.setattr(
            ml_train_tft, "train_and_register_tft", fake_train_and_register_tft
        )

        result = runner.invoke(cli.main, ["train-tft"])

        assert result.exit_code == 1
        assert "no training data found" in result.output


class TestTuneCommand:
    def test_success_reports_best_trial(self, runner, monkeypatch):
        async def fake_tune(regions, **kwargs):
            return ml_tune.TuneResult(
                best_config=ml_train.TrainConfig(hidden_size=256, lr=5e-4),
                best_val_mape=3.1,
                best_run_id="run-best",
                trials=[
                    ml_tune.TuneTrial(
                        hidden_size=128, lr=1e-3, val_mape=5.0, run_id="run-1"
                    ),
                    ml_tune.TuneTrial(
                        hidden_size=256, lr=5e-4, val_mape=3.1, run_id="run-best"
                    ),
                ],
            )

        monkeypatch.setattr(ml_tune, "tune", fake_tune)

        result = runner.invoke(cli.main, ["tune"])

        assert result.exit_code == 0, result.output
        assert "2 trials" in result.output
        assert "run-best" in result.output
        assert "hidden_size=256" in result.output

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_tune(regions, **kwargs):
            raise ValueError("no training data found in the warehouse")

        monkeypatch.setattr(ml_tune, "tune", fake_tune)

        result = runner.invoke(cli.main, ["tune"])

        assert result.exit_code == 1
        assert "no training data found" in result.output


class TestTuneOptunaCommand:
    def _fake_search_result(self, **overrides):
        defaults = dict(
            best_config=ml_train.TrainConfig(
                hidden_size=128, num_layers=2, dropout=0.3, lr=5e-4, batch_size=64
            ),
            best_val_mape=4.2,
            best_run_id="search-run-best",
            best_test_metrics={"test_mape": 4.0},
            trials=[
                ml_tune.OptunaTrialResult(
                    number=0,
                    params={"hidden_size": 128},
                    val_mape=4.2,
                    run_id="search-run-best",
                    pruned=False,
                ),
                ml_tune.OptunaTrialResult(
                    number=1,
                    params={"hidden_size": 64},
                    val_mape=9.9,
                    run_id=None,
                    pruned=True,
                ),
            ],
            n_raw_rows=1000,
            data_source="fct_energy_demand",
            imputed_fraction=None,
        )
        defaults.update(overrides)
        return ml_tune.OptunaTuneResult(**defaults)

    def test_success_runs_search_then_final_retrain_and_registers(
        self, runner, monkeypatch
    ):
        async def fake_tune_optuna(regions, **kwargs):
            return self._fake_search_result()

        captured = {}

        async def fake_train_and_register(model_name, regions, **kwargs):
            captured["model_name"] = model_name
            captured["regions"] = regions
            captured["config"] = kwargs["config"]
            captured["data_source"] = kwargs["data_source"]
            captured["extra_tags"] = kwargs["extra_tags"]
            return ml_train.TrainAndRegisterResult(
                run_id="final-run-1",
                model_version="7",
                test_metrics={"test_mape": 3.8, "test_coverage_calibrated": 0.81},
                final_val_mape=3.9,
            )

        monkeypatch.setattr(ml_tune, "tune_optuna", fake_tune_optuna)
        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["tune-optuna", "--n-trials", "2"])

        assert result.exit_code == 0, result.output
        assert "2 trials (1 pruned)" in result.output
        assert "search-run-best" in result.output
        assert "final-run-1" in result.output
        assert "registered as lstm_demand v7" in result.output
        assert "test_mape=3.80" in result.output
        # The winning search config's hyperparameters really carry over
        # into the final full-budget retrain's config.
        assert captured["config"].hidden_size == 128
        assert captured["config"].num_layers == 2
        assert captured["data_source"] == "fct_energy_demand"
        assert captured["extra_tags"]["optuna_search_run_id"] == "search-run-best"

    def test_no_register_flag_is_threaded_through(self, runner, monkeypatch):
        async def fake_tune_optuna(regions, **kwargs):
            return self._fake_search_result()

        captured = {}

        async def fake_train_and_register(model_name, regions, **kwargs):
            captured["register"] = kwargs["register"]
            return ml_train.TrainAndRegisterResult(
                run_id="final-run-1",
                model_version=None,
                test_metrics={},
                final_val_mape=None,
            )

        monkeypatch.setattr(ml_tune, "tune_optuna", fake_tune_optuna)
        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["tune-optuna", "--no-register"])

        assert result.exit_code == 0, result.output
        assert captured["register"] is False
        assert "not registered (--no-register)" in result.output

    def test_data_source_flag_is_threaded_through_to_both_steps(
        self, runner, monkeypatch
    ):
        search_kwargs = {}
        register_kwargs = {}

        async def fake_tune_optuna(regions, **kwargs):
            search_kwargs.update(kwargs)
            return self._fake_search_result(
                data_source="ml_features_v1", imputed_fraction=0.66
            )

        async def fake_train_and_register(model_name, regions, **kwargs):
            register_kwargs.update(kwargs)
            return ml_train.TrainAndRegisterResult(
                run_id="final-run-1",
                model_version="7",
                test_metrics={},
                final_val_mape=None,
            )

        monkeypatch.setattr(ml_tune, "tune_optuna", fake_tune_optuna)
        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(
            cli.main,
            [
                "tune-optuna",
                "--data-source",
                "ml_features_v1",
                "--train-frac",
                "0.6",
                "--val-frac",
                "0.2",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "imputed_fraction=0.660" in result.output
        assert search_kwargs["data_source"] == "ml_features_v1"
        assert search_kwargs["train_frac"] == 0.6
        assert search_kwargs["val_frac"] == 0.2
        assert register_kwargs["data_source"] == "ml_features_v1"

    def test_search_failure_exits_nonzero_and_does_not_retrain(
        self, runner, monkeypatch
    ):
        async def fake_tune_optuna(regions, **kwargs):
            raise ValueError("no training data found in 'fct_energy_demand'")

        register_called = False

        async def fake_train_and_register(model_name, regions, **kwargs):
            nonlocal register_called
            register_called = True
            raise AssertionError("should not be called when the search fails")

        monkeypatch.setattr(ml_tune, "tune_optuna", fake_tune_optuna)
        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["tune-optuna"])

        assert result.exit_code == 1
        assert "tune-optuna: failed" in result.output
        assert "no training data found" in result.output
        assert register_called is False

    def test_final_retrain_failure_exits_nonzero(self, runner, monkeypatch):
        async def fake_tune_optuna(regions, **kwargs):
            return self._fake_search_result()

        async def fake_train_and_register(model_name, regions, **kwargs):
            raise ValueError("mlflow registry unreachable")

        monkeypatch.setattr(ml_tune, "tune_optuna", fake_tune_optuna)
        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["tune-optuna"])

        assert result.exit_code == 1
        assert "tune-optuna: failed" in result.output
        assert "mlflow registry unreachable" in result.output


class TestEvaluateCommand:
    def test_success_reports_run_and_per_region_reports(self, runner, monkeypatch):
        async def fake_evaluate_and_log(model_name, version, regions, **kwargs):
            return ml_evaluate.EvaluationRunResult(
                run_id="eval-run-1",
                reports=[
                    ml_evaluate.EvaluationReport(
                        model_name="lstm_demand_v1",
                        region="NSW1",
                        horizon=6,
                        n_origins=10,
                        mape=8.5,
                        rmse=120.0,
                        pinball_loss_10=10.0,
                        pinball_loss_50=20.0,
                        pinball_loss_90=10.0,
                        empirical_coverage=0.82,
                    ),
                    ml_evaluate.EvaluationReport(
                        model_name="seasonal_naive",
                        region="NSW1",
                        horizon=6,
                        n_origins=10,
                        mape=6.5,
                        rmse=100.0,
                        pinball_loss_10=8.0,
                        pinball_loss_50=15.0,
                        pinball_loss_90=8.0,
                        empirical_coverage=0.79,
                    ),
                ],
            )

        monkeypatch.setattr(ml_evaluate, "evaluate_and_log", fake_evaluate_and_log)

        result = runner.invoke(cli.main, ["evaluate", "--version", "1"])

        assert result.exit_code == 0, result.output
        assert "eval-run-1" in result.output
        assert "lstm_demand_v1" in result.output
        assert "seasonal_naive" in result.output
        assert "mape=8.50" in result.output

    def test_version_is_required(self, runner):
        result = runner.invoke(cli.main, ["evaluate"])

        assert result.exit_code != 0
        assert "--version" in result.output

    def test_model_name_and_region_options_are_forwarded(self, runner, monkeypatch):
        captured = {}

        async def fake_evaluate_and_log(model_name, version, regions, **kwargs):
            captured["model_name"] = model_name
            captured["version"] = version
            captured["regions"] = list(regions)
            return ml_evaluate.EvaluationRunResult(run_id="run-1", reports=[])

        monkeypatch.setattr(ml_evaluate, "evaluate_and_log", fake_evaluate_and_log)

        result = runner.invoke(
            cli.main,
            [
                "evaluate",
                "--version",
                "3",
                "--model-name",
                "lstm_demand_tft",
                "--region",
                "QLD1",
                "--region",
                "SA1",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["model_name"] == "lstm_demand_tft"
        assert captured["version"] == "3"
        assert captured["regions"] == ["QLD1", "SA1"]

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_evaluate_and_log(model_name, version, regions, **kwargs):
            raise ValueError("no data found in the warehouse")

        monkeypatch.setattr(ml_evaluate, "evaluate_and_log", fake_evaluate_and_log)

        result = runner.invoke(cli.main, ["evaluate", "--version", "1"])

        assert result.exit_code == 1
        assert "no data found" in result.output


class TestEvaluateTftCommand:
    def test_success_reports_run_and_per_region_reports(self, runner, monkeypatch):
        async def fake_evaluate_tft_and_log(model_name, version, regions, **kwargs):
            return ml_evaluate.EvaluationRunResult(
                run_id="eval-tft-1",
                reports=[
                    ml_evaluate.EvaluationReport(
                        model_name="lstm_demand_tft_v1",
                        region="NSW1",
                        horizon=6,
                        n_origins=10,
                        mape=7.2,
                        rmse=115.0,
                        pinball_loss_10=10.0,
                        pinball_loss_50=20.0,
                        pinball_loss_90=10.0,
                        empirical_coverage=0.8,
                    ),
                ],
            )

        monkeypatch.setattr(
            ml_evaluate, "evaluate_tft_and_log", fake_evaluate_tft_and_log
        )

        result = runner.invoke(cli.main, ["evaluate-tft", "--version", "1"])

        assert result.exit_code == 0, result.output
        assert "eval-tft-1" in result.output
        assert "lstm_demand_tft_v1" in result.output
        assert "mape=7.20" in result.output

    def test_defaults_model_name_to_lstm_demand_tft(self, runner, monkeypatch):
        captured = {}

        async def fake_evaluate_tft_and_log(model_name, version, regions, **kwargs):
            captured["model_name"] = model_name
            return ml_evaluate.EvaluationRunResult(run_id="run-1", reports=[])

        monkeypatch.setattr(
            ml_evaluate, "evaluate_tft_and_log", fake_evaluate_tft_and_log
        )

        result = runner.invoke(cli.main, ["evaluate-tft", "--version", "1"])

        assert result.exit_code == 0, result.output
        assert captured["model_name"] == "lstm_demand_tft"

    def test_version_is_required(self, runner):
        result = runner.invoke(cli.main, ["evaluate-tft"])

        assert result.exit_code != 0
        assert "--version" in result.output

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_evaluate_tft_and_log(model_name, version, regions, **kwargs):
            raise ValueError("no data found in the warehouse")

        monkeypatch.setattr(
            ml_evaluate, "evaluate_tft_and_log", fake_evaluate_tft_and_log
        )

        result = runner.invoke(cli.main, ["evaluate-tft", "--version", "1"])

        assert result.exit_code == 1
        assert "no data found" in result.output


class TestEvaluateTimesfmCommand:
    def test_success_reports_run_and_per_region_reports(self, runner, monkeypatch):
        async def fake_evaluate_timesfm_and_log(regions, **kwargs):
            return ml_evaluate.EvaluationRunResult(
                run_id="eval-timesfm-1",
                reports=[
                    ml_evaluate.EvaluationReport(
                        model_name="timesfm",
                        region="WEM",
                        horizon=6,
                        n_origins=8,
                        mape=9.5,
                        rmse=110.0,
                        pinball_loss_10=9.0,
                        pinball_loss_50=18.0,
                        pinball_loss_90=9.0,
                        empirical_coverage=0.8,
                    ),
                ],
            )

        monkeypatch.setattr(
            ml_evaluate, "evaluate_timesfm_and_log", fake_evaluate_timesfm_and_log
        )

        result = runner.invoke(cli.main, ["evaluate-timesfm"])

        assert result.exit_code == 0, result.output
        assert "eval-timesfm-1" in result.output
        assert "timesfm" in result.output
        assert "mape=9.50" in result.output

    def test_options_are_forwarded(self, runner, monkeypatch):
        captured = {}

        async def fake_evaluate_timesfm_and_log(regions, **kwargs):
            captured["regions"] = list(regions)
            captured.update(kwargs)
            return ml_evaluate.EvaluationRunResult(run_id="run-1", reports=[])

        monkeypatch.setattr(
            ml_evaluate, "evaluate_timesfm_and_log", fake_evaluate_timesfm_and_log
        )

        result = runner.invoke(
            cli.main,
            [
                "evaluate-timesfm",
                "--region",
                "WEM",
                "--horizon",
                "12",
                "--n-origins",
                "5",
                "--max-context",
                "256",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["regions"] == ["WEM"]
        assert captured["horizon"] == 12
        assert captured["n_origins"] == 5
        assert captured["max_context"] == 256

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_evaluate_timesfm_and_log(regions, **kwargs):
            raise ValueError("no data found in the warehouse")

        monkeypatch.setattr(
            ml_evaluate, "evaluate_timesfm_and_log", fake_evaluate_timesfm_and_log
        )

        result = runner.invoke(cli.main, ["evaluate-timesfm"])

        assert result.exit_code == 1
        assert "no data found" in result.output


class TestAuthCreateUserCommand:
    def test_success_with_password_flag(self, runner, monkeypatch):
        captured = {}

        async def fake_create_user(db, username, password, role):
            captured.update(username=username, password=password, role=role)
            return "user-123"

        monkeypatch.setattr(auth_service, "create_user", fake_create_user)

        result = runner.invoke(
            cli.main,
            [
                "auth",
                "create-user",
                "--username",
                "diptu",
                "--password",
                "hunter2",
                "--role",
                "admin",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "created 'diptu'" in result.output
        assert "user-123" in result.output
        assert captured == {"username": "diptu", "password": "hunter2", "role": "admin"}

    def test_prompts_for_password_when_not_given(self, runner, monkeypatch):
        async def fake_create_user(db, username, password, role):
            assert password == "prompted-secret"
            return "user-456"

        monkeypatch.setattr(auth_service, "create_user", fake_create_user)

        result = runner.invoke(
            cli.main,
            ["auth", "create-user", "--username", "diptu", "--role", "analyst"],
            input="prompted-secret\nprompted-secret\n",
        )

        assert result.exit_code == 0, result.output
        assert "created 'diptu'" in result.output

    def test_invalid_role_is_rejected_by_click_before_calling_create_user(self, runner):
        result = runner.invoke(
            cli.main,
            [
                "auth",
                "create-user",
                "--username",
                "diptu",
                "--password",
                "x",
                "--role",
                "superadmin",
            ],
        )

        assert result.exit_code != 0
        assert (
            "Invalid value" in result.output
            or "invalid choice" in result.output.lower()
        )

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_create_user(db, username, password, role):
            raise RuntimeError("username already taken")

        monkeypatch.setattr(auth_service, "create_user", fake_create_user)

        result = runner.invoke(
            cli.main,
            [
                "auth",
                "create-user",
                "--username",
                "diptu",
                "--password",
                "x",
                "--role",
                "admin",
            ],
        )

        assert result.exit_code == 1
        assert "username already taken" in result.output
