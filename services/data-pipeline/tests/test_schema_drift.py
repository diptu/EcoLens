from datetime import UTC, datetime

import pytest

from app.service.pipeline import schema_drift

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _live_from(table_name: str, **overrides):
    """A copy of the expected schema for `table_name`, with `overrides`
    applied (col -> (type, nullable) or None to delete the column)."""
    live = dict(schema_drift._EXPECTED_COLUMNS[table_name])
    for col, value in overrides.items():
        if value is None:
            live.pop(col, None)
        else:
            live[col] = value
    return live


def test_no_drift_against_the_expected_schema_itself():
    live = _live_from("aemo_nem_dispatch")

    drifts = schema_drift._diff_table("aemo_nem_dispatch", live)

    assert drifts == []


def test_column_added_is_flagged_low_severity_and_auto_adapted():
    live = _live_from("aemo_nem_dispatch", renewable_pct=("double precision", "YES"))

    drifts = schema_drift._diff_table("aemo_nem_dispatch", live)

    assert len(drifts) == 1
    d = drifts[0]
    assert d["kind"] == "column_added"
    assert d["column_name"] == "renewable_pct"
    assert d["severity"] == "low"
    assert d["auto_adapted"] is True
    assert d["action_required"] is False


def test_column_removed_is_flagged_high_severity_and_actionable():
    live = _live_from("bom_observations", cloud_oktas=None)

    drifts = schema_drift._diff_table("bom_observations", live)

    assert len(drifts) == 1
    d = drifts[0]
    assert d["kind"] == "column_removed"
    assert d["column_name"] == "cloud_oktas"
    assert d["severity"] == "high"
    assert d["auto_adapted"] is False
    assert d["action_required"] is True


def test_safe_type_widening_is_auto_adapted(monkeypatch):
    # None of the 5 real raw.* tables currently have a column whose
    # expected type is on the safe-widening list (they're all
    # numeric/text/timestamptz/uuid/boolean/date already) -- exercise the
    # branch directly against a synthetic expected schema instead of
    # asserting something false about real data.
    monkeypatch.setitem(
        schema_drift._EXPECTED_COLUMNS,
        "aemo_nem_dispatch",
        {
            **schema_drift._EXPECTED_COLUMNS["aemo_nem_dispatch"],
            "demand_mw": ("integer", "YES"),
        },
    )
    live = dict(schema_drift._EXPECTED_COLUMNS["aemo_nem_dispatch"])
    live["demand_mw"] = ("numeric", "YES")

    drifts = schema_drift._diff_table("aemo_nem_dispatch", live)

    assert len(drifts) == 1
    assert drifts[0]["kind"] == "type_changed"
    assert drifts[0]["auto_adapted"] is True
    assert drifts[0]["severity"] == "medium"


def test_unsafe_type_change_is_high_severity_and_actionable():
    live = _live_from("aemo_nem_dispatch")
    live["demand_mw"] = ("text", "YES")

    drifts = schema_drift._diff_table("aemo_nem_dispatch", live)

    assert len(drifts) == 1
    d = drifts[0]
    assert d["kind"] == "type_changed"
    assert d["old_type"] == "numeric"
    assert d["new_type"] == "text"
    assert d["severity"] == "high"
    assert d["auto_adapted"] is False
    assert d["action_required"] is True


def test_nullable_changed_is_low_severity_and_auto_adapted():
    live = _live_from("aemo_nem_dispatch")
    live["source"] = ("text", "NO")  # expected is ("text", "YES")

    drifts = schema_drift._diff_table("aemo_nem_dispatch", live)

    assert len(drifts) == 1
    d = drifts[0]
    assert d["kind"] == "nullable_changed"
    assert d["severity"] == "low"
    assert d["auto_adapted"] is True


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, live_by_table):
        self.live_by_table = live_by_table
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.executed.append((sql, params))

        if "information_schema.columns" in sql:
            table_name = params["table_name"]
            live = self.live_by_table.get(
                table_name, schema_drift._EXPECTED_COLUMNS[table_name]
            )
            rows = [
                {"column_name": col, "data_type": dtype, "is_nullable": nullable}
                for col, (dtype, nullable) in live.items()
            ]
            return _FakeResult(rows)

        if sql.strip().startswith("INSERT INTO meta.schema_drifts"):
            return _FakeResult([])

        if sql.strip().startswith("DELETE FROM meta.schema_drifts"):
            return _FakeResult([])

        raise AssertionError(f"unexpected query: {sql}")


async def test_detect_drift_upserts_and_deletes_reconciled_rows():
    live_by_table = {
        "aemo_nem_dispatch": _live_from(
            "aemo_nem_dispatch", renewable_pct=("double precision", "YES")
        ),
        "aemo_wem_dispatch": dict(schema_drift._EXPECTED_COLUMNS["aemo_wem_dispatch"]),
        "bom_observations": dict(schema_drift._EXPECTED_COLUMNS["bom_observations"]),
        "openelectricity_mix": dict(
            schema_drift._EXPECTED_COLUMNS["openelectricity_mix"]
        ),
        "aemo_holidays": dict(schema_drift._EXPECTED_COLUMNS["aemo_holidays"]),
    }
    session = _FakeSession(live_by_table)

    drifts = await schema_drift.detect_drift(session)

    assert len(drifts) == 1
    assert drifts[0]["column_name"] == "renewable_pct"

    insert_calls = [q for q, _ in session.executed if q.strip().startswith("INSERT")]
    delete_calls = [
        (q, p) for q, p in session.executed if q.strip().startswith("DELETE")
    ]
    assert len(insert_calls) == 1  # only the drifted table gets an upsert
    # Every table's reconcile-delete still runs (clears any previously
    # recorded, now-resolved drift) -- 5 tables total.
    assert len(delete_calls) == 5
    nem_delete = next(
        p for q, p in delete_calls if p["table_name"] == "raw.aemo_nem_dispatch"
    )
    assert nem_delete["still_present_keys"] == ["renewable_pct:::column_added"]
    empty_delete = next(
        p for q, p in delete_calls if p["table_name"] == "raw.aemo_wem_dispatch"
    )
    assert empty_delete["still_present_keys"] == []


async def test_get_recorded_drifts_returns_rows_as_dicts():
    class _RecordedSession:
        async def execute(self, query, params=None):
            return _FakeResult(
                [{"id": "1", "kind": "column_added", "column_name": "renewable_pct"}]
            )

    result = await schema_drift.get_recorded_drifts(_RecordedSession())

    assert result == [
        {"id": "1", "kind": "column_added", "column_name": "renewable_pct"}
    ]


async def test_count_recent_drifts_splits_by_auto_adapted():
    class _CountSession:
        async def execute(self, query, params=None):
            return _FakeResult(
                [{"auto_adapted": True, "cnt": 3}, {"auto_adapted": False, "cnt": 1}]
            )

    counts = await schema_drift.count_recent_drifts(
        _CountSession(), datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert counts == {"total_drifts_24h": 4, "auto_adapted": 3, "needs_action": 1}
