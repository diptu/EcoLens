from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

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


async def test_already_succeeded_checks_window_start_not_started_at(monkeypatch):
    """Regression: this used to check `started_at::date = :day` --
    `started_at` is when the run itself executed (real wall-clock time),
    never the historical `day` a backfill run fetched, so it only ever
    coincidentally matched. `window_start` (now actually populated by
    `registry.run_source`, see its own docstring) is the real fetched
    date and is what this must check instead."""
    captured = {}

    class _QueryCapturingSession:
        async def execute(self, query, params):
            captured["query"] = str(query)
            captured["params"] = params
            return FakeResult(None)

    @asynccontextmanager
    async def _fake_get_session():
        yield _QueryCapturingSession()

    monkeypatch.setattr(backfill, "get_session", _fake_get_session)

    await backfill.already_succeeded("bom", date(2026, 1, 1))

    assert "window_start::date = :day" in captured["query"]
    assert "started_at::date" not in captured["query"]
    assert captured["params"] == {"source": "bom", "day": date(2026, 1, 1)}


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
    """As of 2026-08-05 (`oe` joining `_DATE_RANGE_SOURCES` alongside
    `aemo-nem`/`aemo-wem`/`bom`), every real `BACKFILLABLE_SOURCES` entry
    routes through `start`/`end` -- there's no real source left to
    exercise the `lookback_minutes` branch against. Monkeypatches
    `_DATE_RANGE_SOURCES` to empty so this test can still verify that
    branch in isolation, independent of which real sources currently use
    which path (see `test_backfill_day_routes_bom_through_start_end` and
    the date-range test below for the other branch)."""
    monkeypatch.setattr(backfill, "_DATE_RANGE_SOURCES", ())
    captured = {}

    async def fake_already_succeeded(source, day):
        return False

    async def fake_run_source(key, **kwargs):
        captured["key"] = key
        captured["kwargs"] = kwargs
        return 288

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    outcome = await backfill.backfill_day("oe", date(2026, 1, 1), lookback_minutes=1440)

    assert outcome == "success"
    assert captured == {
        "key": "oe",
        "kwargs": {"triggered_by": "backfill", "lookback_minutes": 1440},
    }


async def test_backfill_day_routes_bom_through_start_end(monkeypatch):
    """Regression: `bom` used to be `lookback_minutes`-only (BoM's own
    API has no date-range query) -- now that `ingest_bom.py` has a real
    `_fetch_historical_range`, `bom` must route through `start`/`end`
    like `aemo-nem`/`aemo-wem`, not silently keep re-fetching "now"."""
    captured = {}

    async def fake_already_succeeded(source, day):
        return False

    async def fake_run_source(key, **kwargs):
        captured["kwargs"] = kwargs
        return 144

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    outcome = await backfill.backfill_day("bom", date(2026, 1, 1))

    assert outcome == "success"
    expected_day = datetime(2026, 1, 1, tzinfo=UTC)
    assert captured["kwargs"] == {
        "triggered_by": "backfill",
        "start": expected_day,
        "end": expected_day,
    }


async def test_backfill_day_routes_oe_through_start_end(monkeypatch):
    """Regression: `oe` used to be `lookback_minutes`-only (there was no
    real per-region/date-anchored query at all before the OE region-join
    blocker fix, `todo-model-training.md`) -- now that
    `ingest_openelectricity.py` has a real `_fetch_historical_range`,
    `oe` must route through `start`/`end` like `aemo-nem`/`aemo-wem`/
    `bom`, not silently keep re-fetching "last N minutes from now"."""
    captured = {}

    async def fake_already_succeeded(source, day):
        return False

    async def fake_run_source(key, **kwargs):
        captured["kwargs"] = kwargs
        return 1716

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    outcome = await backfill.backfill_day("oe", date(2026, 1, 1))

    assert outcome == "success"
    expected_day = datetime(2026, 1, 1, tzinfo=UTC)
    assert captured["kwargs"] == {
        "triggered_by": "backfill",
        "start": expected_day,
        "end": expected_day,
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


async def test_backfill_day_reports_failure_when_already_succeeded_raises(monkeypatch):
    """Regression: a transient Postgres connection drop inside
    `already_succeeded`'s own DB check (real, observed:
    `asyncpg.exceptions.ConnectionDoesNotExistError` ~3h/91 days into a
    370-day `oe` backfill) used to go unhandled -- `already_succeeded`
    was called *before* this function's `try` -- killing the entire
    `backfill()` loop for every remaining day/source instead of just
    this one, silently contradicting this function's own "never raises"
    docstring contract."""

    async def fake_already_succeeded(source, day):
        raise ConnectionError("connection was closed in the middle of operation")

    async def fake_run_source(key, **kwargs):
        raise AssertionError("should not be called when the pre-check itself fails")

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    outcome = await backfill.backfill_day("bom", date(2026, 1, 1))

    assert outcome.startswith("failed:")
    assert "connection was closed" in outcome


async def test_backfill_day_requests_exactly_one_calendar_day_for_date_range_sources(
    monkeypatch,
):
    """`aemo-nem`/`aemo-wem` route through `_fetch_historical_range`,
    which treats `[start.date(), end.date()]` as an INCLUSIVE calendar-
    day range (see that function's own docstring/tests). `start`/`end`
    must resolve to the *same* date here — passing `end=start + 1 day`
    (a half-open-range instinct) would silently fetch two real days
    per single day of backfill, doubling AEMO requests and inflating
    `aemo-wem`'s real 288-rows/day down to a wrong ~576 landed."""
    captured = {}

    async def fake_already_succeeded(source, day):
        return False

    async def fake_run_source(key, **kwargs):
        captured["kwargs"] = kwargs
        return 288

    monkeypatch.setattr(backfill, "already_succeeded", fake_already_succeeded)
    monkeypatch.setattr(backfill, "run_source", fake_run_source)

    await backfill.backfill_day("aemo-wem", date(2026, 8, 1))

    expected_day_start = datetime(2026, 8, 1, tzinfo=UTC)
    assert captured["kwargs"]["start"] == expected_day_start
    assert captured["kwargs"]["end"] == expected_day_start


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
