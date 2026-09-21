from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel
from app.schemas.health.base import ComponentHealth


class HealthResponse(AppBaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(AppBaseModel):
    status: Literal["ready", "not_ready"]
    components: list[ComponentHealth]


class SystemLoadResponse(AppBaseModel):
    """Real host/VM resource pressure, read directly from `/proc` inside
    this container -- `os.getloadavg()`/`/proc/meminfo` reflect the
    whole Linux kernel this container shares with every other service
    in the same docker-compose stack (or the same Docker Desktop VM on
    macOS), not just this one container's own cgroup -- exactly the
    "is the shared box under real pressure" signal the Operational Tasks
    page's "System Load" KPI needs (this platform's own real 2026-08-19
    incident: `api`/`train-worker` repeatedly OOM-killed because the
    Docker Desktop VM's total memory was exhausted, invisible from any
    per-service health check)."""

    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float
    cpu_count: int
    mem_total_mb: float
    mem_available_mb: float
    mem_used_pct: float
