"""Tests for ecolens.warehouse.runner.models (StageResult / RunResult)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ecolens.warehouse.runner.models import RunResult, StageResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestStageResult:
    def test_duration_seconds_is_a_property_not_a_method(self):
        # Regression: the original script monkey-patched this on as a
        # plain method (`s.duration_seconds()`), inconsistent with
        # RunResult's proper @property (`r.duration_seconds`). Fixed
        # to be a real property on both.
        start = _now()
        stage = StageResult(
            name="dbt_build",
            started_at=start,
            finished_at=start + timedelta(seconds=5),
            success=True,
        )
        assert stage.duration_seconds == 5.0
        assert isinstance(type(stage).__dict__["duration_seconds"], property)

    def test_defaults(self):
        now = _now()
        stage = StageResult(name="x", started_at=now, finished_at=now, success=True)
        assert stage.rows_affected == 0
        assert stage.error is None
        assert stage.metrics == {}


class TestRunResult:
    def test_duration_is_zero_for_instant(self):
        now = _now()
        r = RunResult(started_at=now, finished_at=now, success=True)
        assert r.duration_seconds == 0.0

    def test_duration_matches_elapsed_time(self):
        start = _now()
        r = RunResult(
            started_at=start, finished_at=start + timedelta(seconds=48), success=True
        )
        assert r.duration_seconds == 48.0

    def test_to_dict_includes_all_stages(self):
        now = _now()
        r = RunResult(
            started_at=now,
            finished_at=now,
            success=True,
            stages=[
                StageResult(
                    name="source_freshness",
                    started_at=now,
                    finished_at=now,
                    success=True,
                ),
                StageResult(
                    name="dbt_build",
                    started_at=now,
                    finished_at=now,
                    success=True,
                    rows_affected=1234,
                ),
                StageResult(
                    name="data_quality", started_at=now, finished_at=now, success=True
                ),
            ],
        )
        d = r.to_dict()
        assert len(d["stages"]) == 3
        assert d["success"] is True
        assert "duration_seconds" in d
        assert d["stages"][1]["rows_affected"] == 1234

    def test_to_dict_reflects_stage_failure(self):
        now = _now()
        r = RunResult(
            started_at=now,
            finished_at=now,
            success=False,
            stages=[
                StageResult(
                    name="dbt_build",
                    started_at=now,
                    finished_at=now,
                    success=False,
                    error="dbt exited 1",
                ),
            ],
        )
        d = r.to_dict()
        assert d["stages"][0]["success"] is False
        assert d["stages"][0]["error"] == "dbt exited 1"
