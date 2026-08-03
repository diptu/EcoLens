"""Tests for the scripts/backfill.py CLI wrapper.

The script lives outside src/ecolens (it's a standalone entrypoint, not
part of the installed package — see its own docstring), so it's loaded
here via importlib rather than a normal import. The logic it wraps
(`app.service.pipeline.backfill`) has its own full test suite in
test_backfill.py; these tests only cover the wrapper's own job: argument
parsing/validation, wiring, and exit codes.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "backfill.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_script", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


@pytest.fixture
def runner():
    return CliRunner()


async def _fake_backfill_all_success(sources, start, end, lookback_minutes):
    return {(s, start): "success" for s in sources}


def test_from_after_to_is_a_usage_error(script, runner, monkeypatch):
    monkeypatch.setattr(script, "backfill", _fake_backfill_all_success)
    monkeypatch.setattr(script, "run_dbt", lambda *a, **k: 0)

    result = runner.invoke(script.main, ["--from", "2026-07-19", "--to", "2026-07-01"])

    assert result.exit_code != 0
    assert "must not be after" in result.output


def test_defaults_to_all_backfillable_sources(script, runner, monkeypatch):
    captured = {}

    async def fake_backfill(sources, start, end, lookback_minutes):
        captured["sources"] = sources
        return {}

    monkeypatch.setattr(script, "backfill", fake_backfill)
    monkeypatch.setattr(script, "run_dbt", lambda *a, **k: 0)

    result = runner.invoke(script.main, ["--from", "2026-07-19", "--to", "2026-07-19"])

    assert result.exit_code == 0
    assert captured["sources"] == script.BACKFILLABLE_SOURCES


def test_explicit_source_and_lookback_are_forwarded(script, runner, monkeypatch):
    captured = {}

    async def fake_backfill(sources, start, end, lookback_minutes):
        captured.update(
            sources=sources, start=start, end=end, lookback_minutes=lookback_minutes
        )
        return {}

    monkeypatch.setattr(script, "backfill", fake_backfill)
    monkeypatch.setattr(script, "run_dbt", lambda *a, **k: 0)

    result = runner.invoke(
        script.main,
        [
            "--source",
            "bom",
            "--from",
            "2026-07-13",
            "--to",
            "2026-07-19",
            "--lookback-minutes",
            "1440",
        ],
    )

    assert result.exit_code == 0
    assert captured["sources"] == ("bom",)
    assert captured["start"] == date(2026, 7, 13)
    assert captured["end"] == date(2026, 7, 19)
    assert captured["lookback_minutes"] == 1440


def test_runs_dbt_build_by_default(script, runner, monkeypatch):
    monkeypatch.setattr(script, "backfill", _fake_backfill_all_success)
    dbt_calls = []
    monkeypatch.setattr(script, "run_dbt", lambda *a, **k: dbt_calls.append(a) or 0)

    result = runner.invoke(script.main, ["--from", "2026-07-19", "--to", "2026-07-19"])

    assert result.exit_code == 0
    assert len(dbt_calls) == 1
    assert dbt_calls[0][0] == "build"


def test_skip_dbt_flag_skips_the_dbt_build(script, runner, monkeypatch):
    monkeypatch.setattr(script, "backfill", _fake_backfill_all_success)
    dbt_calls = []
    monkeypatch.setattr(script, "run_dbt", lambda *a, **k: dbt_calls.append(a) or 0)

    result = runner.invoke(
        script.main,
        ["--from", "2026-07-19", "--to", "2026-07-19", "--skip-dbt"],
    )

    assert result.exit_code == 0
    assert dbt_calls == []


def test_exits_nonzero_if_any_day_failed(script, runner, monkeypatch):
    async def fake_backfill(sources, start, end, lookback_minutes):
        return {("bom", start): "failed: upstream down", ("oe", start): "success"}

    monkeypatch.setattr(script, "backfill", fake_backfill)
    monkeypatch.setattr(script, "run_dbt", lambda *a, **k: 0)

    result = runner.invoke(script.main, ["--from", "2026-07-19", "--to", "2026-07-19"])

    assert result.exit_code == 1


def test_dbt_failure_does_not_change_exit_code_when_data_backfill_succeeded(
    script, runner, monkeypatch
):
    monkeypatch.setattr(script, "backfill", _fake_backfill_all_success)
    monkeypatch.setattr(script, "run_dbt", lambda *a, **k: 1)

    result = runner.invoke(script.main, ["--from", "2026-07-19", "--to", "2026-07-19"])

    assert result.exit_code == 0
    assert "dbt build failed" in result.output
