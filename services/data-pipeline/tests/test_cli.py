import json

import pytest
from click.testing import CliRunner

from app import cli
from app.service import auth as auth_service
from app.service.ml import train as ml_train
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

    def test_failure_exits_nonzero_and_reports_the_error(self, runner, monkeypatch):
        async def fake_train_and_register(model_name, regions, **kwargs):
            raise ValueError("no training data found in the warehouse")

        monkeypatch.setattr(ml_train, "train_and_register", fake_train_and_register)

        result = runner.invoke(cli.main, ["train"])

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
