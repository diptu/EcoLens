"""`TODO.md` Phase 4: `run_dbt` previously broke on multi-word dbt
subcommands (`source freshness`, `docs generate`, ...) — confirmed live
against the real `dbt` CLI that `--project-dir`/`--profiles-dir`/
`--target` must come after *every* word of the subcommand path, and that
`ecolens-warehouse dbt source freshness` (the CLI's own documented
example) actually calls `run_dbt("source", extra_args=["freshness"])`
once click has parsed it — `subcommand` and `extra_args` arrive
pre-split, not as one string.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.dbt import runner


@pytest.fixture(autouse=True)
def _fake_settings(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: SimpleNamespace(
            dbt_project_dir="/proj", dbt_postgres_env={}
        ),
    )


def _run_and_capture_args(monkeypatch, **kwargs):
    captured = {}

    def fake_run(args, **_kwargs):
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner.run_dbt(**kwargs)
    return captured["args"]


def test_single_word_subcommand_unchanged(monkeypatch):
    args = _run_and_capture_args(monkeypatch, subcommand="run")
    assert args == [
        "dbt",
        "run",
        "--project-dir",
        "/proj",
        "--profiles-dir",
        "/proj",
        "--target",
        "dev",
    ]


def test_multiword_subcommand_as_single_string(monkeypatch):
    """A caller passing the whole path pre-joined (e.g. a test, or a
    future non-CLI caller) — `subcommand.split()` handles it."""
    args = _run_and_capture_args(monkeypatch, subcommand="source freshness")
    assert args == [
        "dbt",
        "source",
        "freshness",
        "--project-dir",
        "/proj",
        "--profiles-dir",
        "/proj",
        "--target",
        "dev",
    ]


def test_multiword_subcommand_as_click_split_extra_arg(monkeypatch):
    """What `ecolens-warehouse dbt source freshness` actually produces
    once click has parsed it: `subcommand="source"`,
    `extra_args=("freshness",)`. Real bug this regression-tests: the
    original implementation put `--project-dir` right after `source`,
    which dbt's CLI rejects (`Error: No such option '--project-dir'`)."""
    args = _run_and_capture_args(
        monkeypatch, subcommand="source", extra_args=["freshness"]
    )
    assert args == [
        "dbt",
        "source",
        "freshness",
        "--project-dir",
        "/proj",
        "--profiles-dir",
        "/proj",
        "--target",
        "dev",
    ]


def test_real_flags_stay_after_global_options_not_consumed_as_path(monkeypatch):
    args = _run_and_capture_args(
        monkeypatch, subcommand="run", extra_args=["--select", "fct_energy_demand"]
    )
    assert args == [
        "dbt",
        "run",
        "--project-dir",
        "/proj",
        "--profiles-dir",
        "/proj",
        "--target",
        "dev",
        "--select",
        "fct_energy_demand",
    ]


def test_multiword_subcommand_with_trailing_flags(monkeypatch):
    """`freshness` (no leading `-`) continues the path; `--select ...`
    (leading `-`) stops path-continuation and stays a trailing flag."""
    args = _run_and_capture_args(
        monkeypatch,
        subcommand="source",
        extra_args=["freshness", "--select", "stg_openelectricity_mix"],
    )
    assert args == [
        "dbt",
        "source",
        "freshness",
        "--project-dir",
        "/proj",
        "--profiles-dir",
        "/proj",
        "--target",
        "dev",
        "--select",
        "stg_openelectricity_mix",
    ]


def test_metric_and_log_labels_use_full_resolved_path(monkeypatch):
    """Regression guard for the labeling fix alongside the arg-order fix
    — `dbt source freshness` and a bare `dbt source` must be
    distinguishable in Prometheus, not both labeled just `"source"`."""
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    duration_mock = MagicMock()
    total_mock = MagicMock()
    captured_labels = {}

    def fake_duration_labels(**kw):
        captured_labels["duration"] = kw
        return duration_mock

    def fake_total_labels(**kw):
        captured_labels["total"] = kw
        return total_mock

    monkeypatch.setattr(
        runner.dbt_run_duration_seconds, "labels", fake_duration_labels
    )
    monkeypatch.setattr(runner.dbt_runs_total, "labels", fake_total_labels)

    runner.run_dbt("source", extra_args=["freshness"])

    assert captured_labels["duration"] == {"subcommand": "source freshness"}
    assert captured_labels["total"]["subcommand"] == "source freshness"
