"""Tests for ecolens.warehouse.runner.dbt_runner.DbtRunner."""

from __future__ import annotations

import shutil

from ecolens.warehouse.runner.dbt_runner import DbtRunner
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings


class TestParseRowCount:
    def test_parses_row_count_from_dbt_summary(self):
        stdout = (
            "1 of 5 OK created table model ...... [OK in 0.42s]\n"
            "Done. 5 tables created, 1234 rows inserted"
        )
        assert DbtRunner._parse_row_count(stdout) == 1234

    def test_returns_zero_when_no_summary(self):
        assert DbtRunner._parse_row_count("") == 0
        assert DbtRunner._parse_row_count("no row count here") == 0

    def test_handles_comma_in_number(self):
        stdout = "Done. 1,234,567 rows ........"
        assert DbtRunner._parse_row_count(stdout) == 1234567


class TestRunGracefulFailure:
    def test_returns_error_stage_result_when_binary_missing(self, tmp_path):
        settings = WarehouseRunnerSettings(dbt_binary="/nonexistent/dbt-binary")
        assert shutil.which(settings.dbt_binary) is None
        runner = DbtRunner(settings)
        result = runner.run(command="build")
        assert result.success is False
        assert result.name == "dbt_build"
        assert "not found" in (result.error or "")

    def test_does_not_raise_when_dbt_path_missing(self, tmp_path):
        settings = WarehouseRunnerSettings(
            dbt_path=tmp_path / "does-not-exist",
            dbt_binary="/nonexistent/dbt-binary",
        )
        # Constructing the runner should just log a warning, not raise.
        DbtRunner(settings)
