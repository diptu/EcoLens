from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from app.retention import mart_floor_monitor

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    """Inspects the raw SQL text to route to the right fixture -- there's
    no ORM here (raw `text()` queries, `TODO.md`'s "prod grade" pass), so
    a fake has to distinguish "which query is this" the same way, not by
    call order alone (`check_mart_floors` issues a variable number of
    queries per mart depending on whether it's empty).
    """

    def __init__(self, current_floors, previous_floors):
        self.current_floors = current_floors
        self.previous_floors = previous_floors
        self.upserts = []

    async def execute(self, query, params=None):
        sql = str(query)
        if sql.strip().startswith("SELECT min("):
            mart = sql.split("raw_marts.")[1].strip()
            return _FakeResult((self.current_floors.get(mart),))
        if "FROM meta.mart_floor_checks" in sql:
            prev = self.previous_floors.get(params["mart"])
            return _FakeResult((prev,) if prev is not None else None)
        if "INSERT INTO meta.mart_floor_checks" in sql:
            self.upserts.append(dict(params))
            return _FakeResult(None)
        raise AssertionError(f"unexpected query: {sql}")


def _wire(monkeypatch, current_floors, previous_floors=None):
    session = _FakeSession(current_floors, previous_floors or {})

    @asynccontextmanager
    async def get_session():
        yield session

    monkeypatch.setattr(mart_floor_monitor, "get_session", get_session)
    return session


def _ts(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


_ALL_EMPTY = dict.fromkeys(mart_floor_monitor._MART_TS_COLUMNS, None)


async def test_first_ever_check_never_reports_a_regression(monkeypatch):
    """No `meta.mart_floor_checks` row yet for any mart -- nothing to
    have regressed *from*."""
    current = {**_ALL_EMPTY, "fct_energy_demand": _ts(1)}
    session = _wire(monkeypatch, current, previous_floors={})

    reports = await mart_floor_monitor.check_mart_floors()

    assert all(not r.regressed for r in reports)
    demand_report = next(r for r in reports if r.mart == "fct_energy_demand")
    assert demand_report.min_ts == _ts(1).isoformat()
    assert session.upserts == [{"mart": "fct_energy_demand", "min_ts": _ts(1)}]


async def test_floor_unchanged_is_not_a_regression(monkeypatch):
    current = {**_ALL_EMPTY, "fct_energy_demand": _ts(1)}
    _wire(monkeypatch, current, previous_floors={"fct_energy_demand": _ts(1)})

    reports = await mart_floor_monitor.check_mart_floors()

    assert next(r for r in reports if r.mart == "fct_energy_demand").regressed is False


async def test_floor_moving_earlier_is_not_a_regression(monkeypatch):
    """More history accumulating (a backfill, or simply more raw.* data
    landing over time) moves the floor *earlier* -- that's the expected,
    healthy direction, not a regression."""
    current = {**_ALL_EMPTY, "fct_energy_demand": _ts(1)}
    _wire(monkeypatch, current, previous_floors={"fct_energy_demand": _ts(5)})

    reports = await mart_floor_monitor.check_mart_floors()

    assert next(r for r in reports if r.mart == "fct_energy_demand").regressed is False


async def test_floor_moving_forward_is_flagged_as_a_regression(monkeypatch):
    """The exact failure mode Phase 1 fixed: a mart's floor moving
    *forward* means it silently lost history."""
    current = {**_ALL_EMPTY, "fct_energy_demand": _ts(10)}
    _wire(monkeypatch, current, previous_floors={"fct_energy_demand": _ts(1)})

    reports = await mart_floor_monitor.check_mart_floors()

    demand_report = next(r for r in reports if r.mart == "fct_energy_demand")
    assert demand_report.regressed is True
    assert demand_report.min_ts == _ts(10).isoformat()


async def test_only_the_regressed_mart_is_flagged_not_every_mart(monkeypatch):
    current = {
        "fct_energy_demand": _ts(10),  # regressed
        "fct_emissions_5min": _ts(1),  # unchanged
        "fct_carbon_intensity": None,  # empty
        "fct_generation_mix": None,  # empty
    }
    previous = {"fct_energy_demand": _ts(1), "fct_emissions_5min": _ts(1)}
    _wire(monkeypatch, current, previous_floors=previous)

    reports = await mart_floor_monitor.check_mart_floors()

    regressed = {r.mart for r in reports if r.regressed}
    assert regressed == {"fct_energy_demand"}


async def test_empty_mart_reports_none_and_is_never_flagged_or_upserted(monkeypatch):
    _wire(monkeypatch, _ALL_EMPTY, previous_floors={})

    reports = await mart_floor_monitor.check_mart_floors()

    assert all(r.min_ts is None and r.regressed is False for r in reports)


async def test_updates_the_prometheus_gauge_for_non_empty_marts_only(monkeypatch):
    from app.core.metrics import mart_min_ts_seconds

    current = {**_ALL_EMPTY, "fct_energy_demand": _ts(1)}
    _wire(monkeypatch, current, previous_floors={})

    await mart_floor_monitor.check_mart_floors()

    assert mart_min_ts_seconds.labels(mart="fct_energy_demand")._value.get() == _ts(
        1
    ).timestamp()
