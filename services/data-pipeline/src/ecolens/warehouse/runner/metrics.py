"""Stage 5: emit structured metrics for downstream observability.

Today: writes a JSON line per run that can be tailed by
promtail/vector -> Loki, or grepped by ops.
Tomorrow: push to prometheus_client.Counter if installed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ecolens.shared.observability.logging import get_logger

from .models import RunResult, StageResult
from .settings import WarehouseRunnerSettings

log = get_logger(__name__)


class MetricsEmitter:
    """Logs structured metrics for downstream observability."""

    def __init__(self, settings: WarehouseRunnerSettings) -> None:
        self.settings = settings
        self.settings.log_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, result: RunResult) -> StageResult:
        started = datetime.now(timezone.utc)
        line = json.dumps(result.to_dict(), default=str)
        log_file = self.settings.log_dir / "warehouse-runs.jsonl"
        with log_file.open("a") as f:
            f.write(line + "\n")

        summary_file = self.settings.log_dir / "warehouse-runs.log"
        summary = (
            f"[{result.finished_at.isoformat()}] "
            f"success={result.success} "
            f"duration={result.duration_seconds:.1f}s "
            f"stages={len(result.stages)} "
            f"rows={sum(s.rows_affected for s in result.stages)}\n"
        )
        with summary_file.open("a") as f:
            f.write(summary)

        finished = datetime.now(timezone.utc)
        log.info(
            "metrics.emitted",
            path=str(log_file),
            success=result.success,
            duration_s=round(result.duration_seconds, 1),
        )
        return StageResult(
            name="metrics",
            started_at=started,
            finished_at=finished,
            success=True,
            metrics={"log_file": str(log_file)},
        )


__all__ = ["MetricsEmitter"]
