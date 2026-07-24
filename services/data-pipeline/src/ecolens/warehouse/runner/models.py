"""Result types shared by every stage and the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StageResult:
    """Result of a single pipeline stage."""

    name: str
    started_at: datetime
    finished_at: datetime
    success: bool
    rows_affected: int = 0
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass
class RunResult:
    """Result of a full warehouse run."""

    started_at: datetime
    finished_at: datetime
    success: bool
    stages: list[StageResult] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": round(self.duration_seconds, 2),
            "success": self.success,
            "stages": [
                {
                    "name": s.name,
                    "started_at": s.started_at.isoformat(),
                    "finished_at": s.finished_at.isoformat(),
                    "success": s.success,
                    "rows_affected": s.rows_affected,
                    "error": s.error,
                    "metrics": s.metrics,
                }
                for s in self.stages
            ],
        }


__all__ = ["StageResult", "RunResult"]
