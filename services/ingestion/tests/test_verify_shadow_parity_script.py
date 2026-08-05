"""Tests for scripts/verify_shadow_parity.py.

Loaded via importlib -- the script lives outside `app/` (a standalone
entrypoint, not part of the installed package, same reasoning as
data-pipeline's `scripts/backfill.py`/`test_backfill_script.py`).
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

pytestmark = pytest.mark.anyio

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "verify_shadow_parity.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_shadow_parity", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules *before* exec_module -- the script's
    # `@dataclass`-decorated `_GroupStats` (with `from __future__ import
    # annotations`, so its field types are strings) resolves them via
    # `sys.modules[cls.__module__]` at class-definition time; without
    # this, that lookup gets `None` and dataclass's own field-type
    # introspection blows up with `'NoneType' object has no attribute
    # '__dict__'`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_pct_delta_is_zero_for_identical_values(script):
    assert script._pct_delta(10, 10) == 0.0


def test_pct_delta_handles_a_zero_real_baseline(script):
    assert script._pct_delta(0, 0) == 0.0
    assert script._pct_delta(5, 0) == 100.0


def test_pct_delta_computes_relative_percentage(script):
    assert script._pct_delta(110, 100) == pytest.approx(10.0)
    assert script._pct_delta(90, 100) == pytest.approx(10.0)


def test_daterange_is_inclusive_of_both_ends(script):
    days = list(script._daterange(date(2026, 1, 1), date(2026, 1, 3)))
    assert days == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class _FakeSession:
    def __init__(self, log_rows_by_trigger, anomaly_counts_by_run_id):
        self._log_rows_by_trigger = log_rows_by_trigger
        self._anomaly_counts_by_run_id = anomaly_counts_by_run_id

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        if "FROM meta._ingest_log" in sql:
            rows = self._log_rows_by_trigger.get(params["trigger"], [])
            return _FakeResult(rows)
        if "FROM meta.anomalies" in sql:
            total = sum(
                self._anomaly_counts_by_run_id.get(run_id, 0)
                for run_id in params["run_ids"]
            )
            return _FakeResult([(total,)])
        raise AssertionError(f"unexpected query: {sql}")


async def test_collect_aggregates_rows_landed_and_anomalies(script, monkeypatch):
    log_rows = {
        "shadow": [
            {
                "id": "run-1",
                "status": "staged",
                "rows_landed": 100,
                "circuit_breaker_state": "closed",
            }
        ]
    }
    session = _FakeSession(log_rows, {"run-1": 3})

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(script, "get_session", fake_get_session)

    stats = await script._collect("bom", date(2026, 1, 1), "shadow")

    assert stats.runs == 1
    assert stats.rows_landed == 100
    assert stats.anomalies_flagged == 3
    assert stats.statuses == {"staged": 1}
    assert stats.circuit_states == {"closed": 1}


async def test_collect_returns_zeroed_stats_for_no_runs(script, monkeypatch):
    session = _FakeSession({}, {})

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(script, "get_session", fake_get_session)

    stats = await script._collect("bom", date(2026, 1, 1), "shadow")

    assert stats.runs == 0
    assert stats.rows_landed == 0
    assert stats.anomalies_flagged == 0


async def test_verify_reports_within_tolerance_when_counts_match(script, monkeypatch):
    log_rows = {
        "shadow": [
            {
                "id": "run-1",
                "status": "staged",
                "rows_landed": 100,
                "circuit_breaker_state": "closed",
            }
        ],
        "schedule": [
            {
                "id": "run-2",
                "status": "staged",
                "rows_landed": 100,
                "circuit_breaker_state": "closed",
            }
        ],
    }
    session = _FakeSession(log_rows, {})

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(script, "get_session", fake_get_session)

    passed = await script._verify(
        "bom", date(2026, 1, 1), date(2026, 1, 1), "schedule", tolerance_pct=1.0
    )

    assert passed is True


async def test_verify_fails_when_deltas_exceed_tolerance(script, monkeypatch):
    log_rows = {
        "shadow": [
            {
                "id": "run-1",
                "status": "staged",
                "rows_landed": 50,
                "circuit_breaker_state": "closed",
            }
        ],
        "schedule": [
            {
                "id": "run-2",
                "status": "staged",
                "rows_landed": 100,
                "circuit_breaker_state": "closed",
            }
        ],
    }
    session = _FakeSession(log_rows, {})

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(script, "get_session", fake_get_session)

    passed = await script._verify(
        "bom", date(2026, 1, 1), date(2026, 1, 1), "schedule", tolerance_pct=1.0
    )

    assert passed is False


def test_unknown_source_is_a_usage_error(script, runner, monkeypatch):
    result = runner.invoke(
        script.main,
        ["--source", "nonexistent", "--from", "2026-01-01", "--to", "2026-01-01"],
    )

    assert result.exit_code != 0


def test_from_after_to_is_a_usage_error(script, runner):
    result = runner.invoke(
        script.main,
        ["--source", "bom", "--from", "2026-01-08", "--to", "2026-01-01"],
    )

    assert result.exit_code != 0
    assert "must not be after" in result.output


def test_exits_nonzero_when_verify_reports_out_of_tolerance(
    script, runner, monkeypatch
):
    async def fake_verify(source, start, end, against, tolerance_pct):
        return False

    monkeypatch.setattr(script, "_verify", fake_verify)

    result = runner.invoke(
        script.main,
        ["--source", "bom", "--from", "2026-01-01", "--to", "2026-01-01"],
    )

    assert result.exit_code == 1


def test_exits_zero_when_verify_reports_within_tolerance(script, runner, monkeypatch):
    async def fake_verify(source, start, end, against, tolerance_pct):
        return True

    monkeypatch.setattr(script, "_verify", fake_verify)

    result = runner.invoke(
        script.main,
        ["--source", "bom", "--from", "2026-01-01", "--to", "2026-01-01"],
    )

    assert result.exit_code == 0
