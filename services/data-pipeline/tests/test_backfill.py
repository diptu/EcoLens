from contextlib import asynccontextmanager
from datetime import date

import pytest

from app.service.pipeline import backfill

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_backfillable_sources_excludes_holidays():
    assert "holidays" not in backfill.BACKFILLABLE_SOURCES
    assert set(backfill.BACKFILLABLE_SOURCES) == {"oe", "aemo-nem", "aemo-wem", "bom"}


def test_daterange_is_inclusive_of_both_ends():
    days = list(backfill.daterange(date(2026, 1, 1), date(2026, 1, 3)))
    assert days == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def test_daterange_single_day():
    days = list(backfill.daterange(date(2026, 1, 1), date(2026, 1, 1)))
    assert days == [date(2026, 1, 1)]


class FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeSession:
    def __init__(self, row=None):
        self._row = row
        self.executed_params = None

    async def execute(self, query, params):
        self.executed_params = params
        return FakeResult(self._row)


def _fake_get_session_factory(row):
    @asynccontextmanager
    async def _fake_get_session():
        yield FakeSession(row)

    return _fake_get_session


async def test_already_succeeded_true_when_a_row_exists(monkeypatch):
    monkeypatch.setattr(backfill, "get_session", _fake_get_session_factory(row=(1,)))

    result = await backfill.already_succeeded("bom", date(2026, 1, 1))

    assert result is True


async def test_already_succeeded_false_when_no_row(monkeypatch):
    monkeypatch.setattr(backfill, "get_session", _fake_get_session_factory(row=None))

    result = await backfill.already_succeeded("bom", date(2026, 1, 1))

    assert result is False


async def test_backfill_day_skips_when_already_succeeded(monkeypatch):
    async def fake_already_succeeded(source, day):
        return True

    async def fake_run_source(key, **kwargs):
        raise AssertionError("should not be called when already succeeded")

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    outcome = await backfill.backfill_day("bom", date(2026, 1, 1))

    assert outcome == "skipped"


async def test_backfill_day_runs_when_not_yet_succeeded(monkeypatch):
    captured = {}

    async def fake_already_succeeded(source, day):
        return False

    async def fake_run_source(key, **kwargs):
        captured["key"] = key
        captured["kwargs"] = kwargs
        return 288

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    outcome = await backfill.backfill_day(
        "bom", date(2026, 1, 1), lookback_minutes=1440
    )

    assert outcome == "success"
    assert captured == {
        "key": "bom",
        "kwargs": {"triggered_by": "backfill", "lookback_minutes": 1440},
    }


async def test_backfill_day_reports_failure_without_raising(monkeypatch):
    async def fake_already_succeeded(source, day):
        return False

    async def fake_run_source(key, **kwargs):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    outcome = await backfill.backfill_day("bom", date(2026, 1, 1))

    assert outcome == "failed: upstream is down"


async def test_backfill_covers_every_source_and_day_in_the_range(monkeypatch):
    calls = []

    async def fake_backfill_day(
        key, day, lookback_minutes=backfill.DEFAULT_LOOKBACK_MINUTES
    ):
        calls.append((key, day))
        return "success"

    monkeypatch.setattr(backfill, "backfill_day", fake_backfill_day)

    results = await backfill.backfill(
        ("bom", "aemo-nem"), date(2026, 1, 1), date(2026, 1, 2)
    )

    assert set(calls) == {
        ("bom", date(2026, 1, 1)),
        ("bom", date(2026, 1, 2)),
        ("aemo-nem", date(2026, 1, 1)),
        ("aemo-nem", date(2026, 1, 2)),
    }
    assert all(outcome == "success" for outcome in results.values())
