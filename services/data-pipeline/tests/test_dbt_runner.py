from unittest.mock import MagicMock

import pytest

from app.service import dbt_runner as runner
from app.core.metrics import dbt_run_duration_seconds, dbt_runs_total


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def test_missing_dbt_binary_returns_127(monkeypatch):
    def raise_not_found(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(runner.subprocess, "run", raise_not_found)

    exit_code = runner.run_dbt("build", "/some/project")

    assert exit_code == 127


def test_successful_run_returns_zero_and_records_success_metric(monkeypatch):
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: MagicMock(returncode=0, stdout="ok", stderr=""),
    )
    before = _counter_value(dbt_runs_total, subcommand="build", outcome="success")

    exit_code = runner.run_dbt("build", "/some/project", target="prod")

    assert exit_code == 0
    assert (
        _counter_value(dbt_runs_total, subcommand="build", outcome="success")
        == before + 1
    )


def test_failed_run_returns_nonzero_and_records_failure_metric(monkeypatch):
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: MagicMock(returncode=1, stdout="", stderr="compilation error"),
    )
    before = _counter_value(dbt_runs_total, subcommand="test", outcome="failure")

    exit_code = runner.run_dbt("test", "/some/project")

    assert exit_code == 1
    assert (
        _counter_value(dbt_runs_total, subcommand="test", outcome="failure")
        == before + 1
    )


def test_run_builds_the_expected_dbt_command(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_dbt(
        "run", "/proj", target="dev", extra_args=["--select", "stg_aemo_nem"]
    )

    assert captured["args"] == [
        "dbt",
        "run",
        "--project-dir",
        "/proj",
        "--profiles-dir",
        "/proj",
        "--target",
        "dev",
        "--select",
        "stg_aemo_nem",
    ]


def test_duration_histogram_records_an_observation(monkeypatch):
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: MagicMock(returncode=0, stdout="", stderr=""),
    )
    before = dbt_run_duration_seconds.labels(subcommand="seed")._sum.get()

    runner.run_dbt("seed", "/proj")

    assert dbt_run_duration_seconds.labels(subcommand="seed")._sum.get() >= before


@pytest.mark.parametrize("subcommand", ["build", "run", "test"])
def test_various_subcommands_are_passed_through(monkeypatch, subcommand):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_dbt(subcommand, "/proj")

    assert captured["args"][1] == subcommand


def test_derived_postgres_env_vars_are_passed_to_the_subprocess(monkeypatch):
    """Regression: `dbt/ecolens/profiles.yml` reads POSTGRES_* as raw OS
    env vars, entirely separate from `Settings.database_url` -- without
    this, a DATABASE_URL-only deployment (the normal case everywhere
    else in this app) left dbt silently falling back to its own
    `localhost` defaults instead of the real database."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["env"] = kwargs.get("env")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/d")
    from app.core.config import get_settings

    get_settings.cache_clear()

    runner.run_dbt("build", "/proj")

    assert captured["env"]["POSTGRES_HOST"] == "h"
    assert captured["env"]["POSTGRES_PORT"] == "1"
    assert captured["env"]["POSTGRES_USER"] == "u"
    assert captured["env"]["POSTGRES_PASSWORD"] == "p"
    assert captured["env"]["POSTGRES_DB"] == "d"
    get_settings.cache_clear()


def test_an_explicitly_set_postgres_env_var_is_not_overridden(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["env"] = kwargs.get("env")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/d")
    monkeypatch.setenv("POSTGRES_HOST", "operator-chosen-host")
    from app.core.config import get_settings

    get_settings.cache_clear()

    runner.run_dbt("build", "/proj")

    assert captured["env"]["POSTGRES_HOST"] == "operator-chosen-host"
    get_settings.cache_clear()
