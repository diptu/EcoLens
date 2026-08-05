import json

import pytest
from click.testing import CliRunner

from app import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_help_lists_all_subcommand_groups(runner):
    result = runner.invoke(cli.main, ["--help"])

    assert result.exit_code == 0
    assert "consume" in result.output
    assert "prune" in result.output
    assert "export-and-prune" in result.output
    assert "vacuum" in result.output
    assert "check-size" in result.output
    assert "dbt" in result.output
    assert "serve" in result.output
    assert "health" in result.output


def test_health_prints_the_same_shape_as_the_api_endpoint(runner):
    result = runner.invoke(cli.main, ["health"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "ok"}


def test_version_flag(runner):
    result = runner.invoke(cli.main, ["--version"])

    assert result.exit_code == 0
    assert "ecolens-warehouse" in result.output


class TestPruneCommand:
    def test_reports_nothing_eligible(self, runner, monkeypatch):
        from app.retention import pruning

        async def fake_prune(days):
            return {}

        monkeypatch.setattr(pruning, "prune_raw_tables", fake_prune)

        result = runner.invoke(cli.main, ["prune"])

        assert result.exit_code == 0
        assert "Nothing eligible" in result.output

    def test_reports_rows_pruned_per_table(self, runner, monkeypatch):
        from app.retention import pruning

        captured = {}

        async def fake_prune(days):
            captured["days"] = days
            return {"bom_observations": 40, "aemo_nem_dispatch": 12}

        monkeypatch.setattr(pruning, "prune_raw_tables", fake_prune)

        result = runner.invoke(cli.main, ["prune", "--days", "30"])

        assert result.exit_code == 0
        assert captured["days"] == 30
        assert "aemo_nem_dispatch: 12 rows pruned" in result.output
        assert "bom_observations: 40 rows pruned" in result.output


class TestExportAndPruneCommand:
    def test_reports_nothing_eligible(self, runner, monkeypatch):
        from app.retention import cold_storage

        async def fake_export_and_prune(days):
            return {}

        monkeypatch.setattr(cold_storage, "export_and_prune", fake_export_and_prune)

        result = runner.invoke(cli.main, ["export-and-prune"])

        assert result.exit_code == 0
        assert "Nothing eligible" in result.output

    def test_reports_exported_and_pruned_counts(self, runner, monkeypatch):
        from app.retention import cold_storage

        async def fake_export_and_prune(days):
            return {"bom_observations": {"exported": 40, "pruned": 40}}

        monkeypatch.setattr(cold_storage, "export_and_prune", fake_export_and_prune)

        result = runner.invoke(cli.main, ["export-and-prune"])

        assert result.exit_code == 0
        assert "bom_observations: exported 40, pruned 40" in result.output


class TestVacuumCommand:
    def test_reports_the_vacuumed_tables(self, runner, monkeypatch):
        from app.retention import vacuum

        async def fake_vacuum():
            return ["aemo_nem_dispatch", "bom_observations"]

        monkeypatch.setattr(vacuum, "vacuum_analyze_raw_tables", fake_vacuum)

        result = runner.invoke(cli.main, ["vacuum"])

        assert result.exit_code == 0
        assert "aemo_nem_dispatch" in result.output
        assert "bom_observations" in result.output


class TestDbtCommand:
    def test_runs_the_given_subcommand_and_prints_output(self, runner, monkeypatch):
        from app.dbt import runner as dbt_runner

        captured = {}

        def fake_run_dbt(subcommand, target="dev", extra_args=None):
            captured["subcommand"] = subcommand
            captured["target"] = target
            captured["extra_args"] = extra_args
            return 0, "dbt output here"

        monkeypatch.setattr(dbt_runner, "run_dbt", fake_run_dbt)

        result = runner.invoke(cli.main, ["dbt", "run"])

        assert result.exit_code == 0
        assert captured["subcommand"] == "run"
        assert captured["target"] == "dev"
        assert "dbt output here" in result.output

    def test_exits_nonzero_on_a_failed_dbt_run(self, runner, monkeypatch):
        from app.dbt import runner as dbt_runner

        def fake_run_dbt(subcommand, target="dev", extra_args=None):
            return 1, "dbt failed"

        monkeypatch.setattr(dbt_runner, "run_dbt", fake_run_dbt)

        result = runner.invoke(cli.main, ["dbt", "test"])

        assert result.exit_code == 1
        assert "dbt failed" in result.output

    def test_forwards_target_option(self, runner, monkeypatch):
        from app.dbt import runner as dbt_runner

        captured = {}

        def fake_run_dbt(subcommand, target="dev", extra_args=None):
            captured["target"] = target
            return 0, ""

        monkeypatch.setattr(dbt_runner, "run_dbt", fake_run_dbt)

        runner.invoke(cli.main, ["dbt", "run", "--target", "prod"])

        assert captured["target"] == "prod"


class TestCheckSizeCommand:
    def test_exits_zero_when_ok(self, runner, monkeypatch):
        from app.retention import size_monitor

        async def fake_check():
            return size_monitor.SizeReport(
                size_bytes=100 * 1024 * 1024,
                limit_bytes=500 * 1024 * 1024,
                pct_used=0.2,
                severity="ok",
            )

        monkeypatch.setattr(size_monitor, "check_database_size", fake_check)

        result = runner.invoke(cli.main, ["check-size"])

        assert result.exit_code == 0
        assert "ok" in result.output

    def test_exits_nonzero_when_warning_or_worse(self, runner, monkeypatch):
        from app.retention import size_monitor

        async def fake_check():
            return size_monitor.SizeReport(
                size_bytes=450 * 1024 * 1024,
                limit_bytes=500 * 1024 * 1024,
                pct_used=0.9,
                severity="warning",
            )

        monkeypatch.setattr(size_monitor, "check_database_size", fake_check)

        result = runner.invoke(cli.main, ["check-size"])

        assert result.exit_code != 0
        assert "warning" in result.output
