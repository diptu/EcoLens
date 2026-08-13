import json

import pytest
from click.testing import CliRunner

from app import cli
from app.service.pipeline.tasks import registry


@pytest.fixture
def runner():
    return CliRunner()


def test_help_lists_all_subcommand_groups(runner):
    result = runner.invoke(cli.main, ["--help"])

    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "backfill" in result.output
    assert "prune-staging" in result.output
    assert "merge-staging" in result.output
    assert "train-anomaly-model" in result.output
    assert "worker" in result.output
    assert "beat" in result.output
    assert "serve" in result.output
    assert "health" in result.output


def test_health_prints_the_same_shape_as_the_api_endpoint(runner):
    result = runner.invoke(cli.main, ["health"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "ok"}


def test_version_flag(runner):
    result = runner.invoke(cli.main, ["--version"])

    assert result.exit_code == 0
    assert "ecolens-ingestion" in result.output


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

    def test_triggered_by_schedule_is_passed_through(self, runner, monkeypatch):
        # Unlike data-pipeline's identical CLI, `--triggered-by schedule`
        # doesn't check a paused-pipeline flag first -- that admin
        # feature (`app.service.pipelines`) wasn't ported (see cli.py's
        # own module docstring for the trigger-only scoping decision).
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["kwargs"] = kwargs
            return 5

        monkeypatch.setattr(cli, "run_source", fake_run_source)

        result = runner.invoke(
            cli.main, ["ingest", "bom", "--triggered-by", "schedule"]
        )

        assert result.exit_code == 0
        assert captured["kwargs"]["triggered_by"] == "schedule"
        assert "bom: 5 rows staged" in result.output

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


class TestBackfillCommand:
    def test_from_after_to_is_a_usage_error(self, runner, monkeypatch):
        result = runner.invoke(
            cli.main,
            ["backfill", "--from", "2026-01-08", "--to", "2026-01-01"],
        )

        assert result.exit_code != 0
        assert "must not be after" in result.output

    def test_defaults_to_all_backfillable_sources(self, runner, monkeypatch):
        from app.service.pipeline import backfill as backfill_module

        captured = {}

        async def fake_backfill(sources, start, end, lookback_minutes):
            captured["sources"] = sources
            return {}

        monkeypatch.setattr(cli, "run_backfill_range", fake_backfill)

        result = runner.invoke(
            cli.main, ["backfill", "--from", "2026-01-01", "--to", "2026-01-01"]
        )

        assert result.exit_code == 0
        assert captured["sources"] == backfill_module.BACKFILLABLE_SOURCES

    def test_reports_each_outcome_and_exits_nonzero_on_failure(
        self, runner, monkeypatch
    ):
        from datetime import date

        async def fake_backfill(sources, start, end, lookback_minutes):
            return {("bom", date(2026, 1, 1)): "failed: upstream down"}

        monkeypatch.setattr(cli, "run_backfill_range", fake_backfill)

        result = runner.invoke(
            cli.main, ["backfill", "--from", "2026-01-01", "--to", "2026-01-01"]
        )

        assert result.exit_code == 1
        assert "2026-01-01 bom: failed: upstream down" in result.output


class TestPruneStagingCommand:
    def test_reports_nothing_eligible(self, runner, monkeypatch):
        from app.service.pipeline import retention

        async def fake_prune(days):
            return {}

        monkeypatch.setattr(retention, "prune_synced_history", fake_prune)

        result = runner.invoke(cli.main, ["prune-staging"])

        assert result.exit_code == 0
        assert "Nothing eligible" in result.output

    def test_reports_rows_pruned_per_source(self, runner, monkeypatch):
        from app.service.pipeline import retention

        captured = {}

        async def fake_prune(days):
            captured["days"] = days
            return {"bom": 120, "aemo_nem": 40}

        monkeypatch.setattr(retention, "prune_synced_history", fake_prune)

        result = runner.invoke(cli.main, ["prune-staging", "--days", "7"])

        assert result.exit_code == 0
        assert captured["days"] == 7
        assert "aemo_nem: 40 rows pruned" in result.output
        assert "bom: 120 rows pruned" in result.output

    def test_defaults_days_to_none_so_the_command_falls_back(self, runner, monkeypatch):
        from app.service.pipeline import retention

        captured = {}

        async def fake_prune(days):
            captured["days"] = days
            return {}

        monkeypatch.setattr(retention, "prune_synced_history", fake_prune)

        runner.invoke(cli.main, ["prune-staging"])

        assert captured["days"] == retention.DEFAULT_RETENTION_DAYS


class TestMergeStagingCommand:
    def test_reports_rows_merged(self, runner, monkeypatch, tmp_path):
        from app.service.pipeline import duckdb_staging

        captured = {}
        scratch_file = tmp_path / "scratch.duckdb"
        scratch_file.write_bytes(b"")

        def fake_merge(source_file, table):
            captured["source_file"] = source_file
            captured["table"] = table
            return 42

        monkeypatch.setattr(duckdb_staging, "merge_staging_file", fake_merge)

        result = runner.invoke(
            cli.main, ["merge-staging", "aemo-nem", "--from", str(scratch_file)]
        )

        assert result.exit_code == 0
        assert "aemo-nem: 42 rows merged" in result.output
        assert captured["table"] == registry.SOURCES["aemo-nem"].table

    def test_rejects_an_unknown_source(self, runner, tmp_path):
        scratch_file = tmp_path / "scratch.duckdb"
        scratch_file.write_bytes(b"")

        result = runner.invoke(
            cli.main,
            ["merge-staging", "not-a-real-source", "--from", str(scratch_file)],
        )

        assert result.exit_code != 0

    def test_rejects_a_missing_from_path(self, runner, tmp_path):
        result = runner.invoke(
            cli.main,
            ["merge-staging", "aemo-nem", "--from", str(tmp_path / "nope.duckdb")],
        )

        assert result.exit_code != 0


class TestTrainAnomalyModelCommand:
    def test_reports_a_skip_when_training_was_skipped(self, runner, monkeypatch):
        from app.service.pipeline import ml_anomaly

        async def fake_train_and_publish(source, table):
            return None

        monkeypatch.setattr(ml_anomaly, "train_and_publish", fake_train_and_publish)

        result = runner.invoke(cli.main, ["train-anomaly-model", "bom"])

        assert result.exit_code == 0
        assert "not enough history" in result.output

    def test_reports_a_summary_on_success(self, runner, monkeypatch):
        from app.service.pipeline import ml_anomaly

        captured = {}

        async def fake_train_and_publish(source, table):
            captured["source"] = source
            captured["table"] = table
            return {
                "source": source,
                "rows_trained": 500,
                "columns": ["temp_c", "humidity_pct"],
                "object_storage_key": "models/anomaly/bom.joblib",
            }

        monkeypatch.setattr(ml_anomaly, "train_and_publish", fake_train_and_publish)

        result = runner.invoke(cli.main, ["train-anomaly-model", "bom"])

        assert result.exit_code == 0
        assert captured == {"source": "bom", "table": "bom_observations"}
        assert "500 rows" in result.output
        assert "models/anomaly/bom.joblib" in result.output

    def test_unknown_source_is_a_usage_error(self, runner):
        result = runner.invoke(cli.main, ["train-anomaly-model", "nonexistent"])

        assert result.exit_code != 0


class TestWorkerAndBeatCommands:
    def test_worker_starts_celery_with_the_worker_subcommand(self, runner, monkeypatch):
        from app.celery_app import celery_app

        captured = {}
        monkeypatch.setattr(
            celery_app, "start", lambda argv: captured.update(argv=argv)
        )

        runner.invoke(cli.main, ["worker"])

        assert captured["argv"] == ["worker"]

    def test_worker_forwards_extra_args_to_celery(self, runner, monkeypatch):
        from app.celery_app import celery_app

        captured = {}
        monkeypatch.setattr(
            celery_app, "start", lambda argv: captured.update(argv=argv)
        )

        runner.invoke(cli.main, ["worker", "--loglevel=info", "--concurrency=2"])

        assert captured["argv"] == ["worker", "--loglevel=info", "--concurrency=2"]

    def test_beat_starts_celery_with_the_beat_subcommand(self, runner, monkeypatch):
        from app.celery_app import celery_app

        captured = {}
        monkeypatch.setattr(
            celery_app, "start", lambda argv: captured.update(argv=argv)
        )

        runner.invoke(cli.main, ["beat", "--loglevel=info"])

        assert captured["argv"] == ["beat", "--loglevel=info"]
