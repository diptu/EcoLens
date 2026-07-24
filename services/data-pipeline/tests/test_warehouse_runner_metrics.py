"""Tests for ecolens.warehouse.runner.metrics.MetricsEmitter."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ecolens.warehouse.runner.metrics import MetricsEmitter
from ecolens.warehouse.runner.models import RunResult, StageResult
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings


def _make_run_result(*, success: bool = True) -> RunResult:
    now = datetime.now(timezone.utc)
    return RunResult(
        started_at=now,
        finished_at=now,
        success=success,
        stages=[
            StageResult(
                name="source_freshness",
                started_at=now,
                finished_at=now,
                success=True,
                metrics={"sources": [], "all_fresh": True},
            ),
            StageResult(
                name="dbt_build",
                started_at=now,
                finished_at=now,
                success=success,
                rows_affected=1234,
            ),
            StageResult(
                name="data_quality",
                started_at=now,
                finished_at=now,
                success=True,
                metrics={"violations": [], "violation_count": 0},
            ),
        ],
    )


class TestEmit:
    def test_creates_log_dir_on_init(self, tmp_path):
        log_dir = tmp_path / "nested" / "log"
        MetricsEmitter(WarehouseRunnerSettings(log_dir=log_dir))
        assert log_dir.exists()

    def test_writes_jsonl_and_summary_log(self, tmp_path):
        emitter = MetricsEmitter(WarehouseRunnerSettings(log_dir=tmp_path))
        result = _make_run_result()
        stage = emitter.emit(result)

        assert stage.success is True
        jsonl = tmp_path / "warehouse-runs.jsonl"
        summary = tmp_path / "warehouse-runs.log"
        assert jsonl.exists()
        assert summary.exists()

    def test_jsonl_line_is_parseable_and_matches_run(self, tmp_path):
        emitter = MetricsEmitter(WarehouseRunnerSettings(log_dir=tmp_path))
        result = _make_run_result()
        emitter.emit(result)

        line = (tmp_path / "warehouse-runs.jsonl").read_text().strip()
        parsed = json.loads(line)
        assert len(parsed["stages"]) == 3
        assert parsed["success"] is True

    def test_summary_log_is_human_readable(self, tmp_path):
        emitter = MetricsEmitter(WarehouseRunnerSettings(log_dir=tmp_path))
        emitter.emit(_make_run_result())
        content = (tmp_path / "warehouse-runs.log").read_text()
        assert "success=True" in content
        assert "duration=" in content
        assert "rows=1234" in content

    def test_multiple_emits_append_rather_than_overwrite(self, tmp_path):
        emitter = MetricsEmitter(WarehouseRunnerSettings(log_dir=tmp_path))
        emitter.emit(_make_run_result())
        emitter.emit(_make_run_result())
        lines = (tmp_path / "warehouse-runs.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_reflects_failure_in_summary(self, tmp_path):
        emitter = MetricsEmitter(WarehouseRunnerSettings(log_dir=tmp_path))
        emitter.emit(_make_run_result(success=False))
        content = (tmp_path / "warehouse-runs.log").read_text()
        assert "success=False" in content
