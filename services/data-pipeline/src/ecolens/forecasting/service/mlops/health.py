"""ECO-116 (health snapshot): last-trained time, last-eval metrics, and
current Production version, read straight from the MLflow run behind
whatever the `production` alias currently points at -- no separate
state store, since the registry + its run metadata already is the
source of truth. This is what the observability stack scrapes, and
what `forecast-api`'s `/health` (ECO-T03) will eventually surface once
it has a model loader to report on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .registry import ModelRegistry


@dataclass(frozen=True)
class HealthSnapshot:
    model_name: str
    alias: str
    production_version: str | None
    last_trained_at: datetime | None
    last_eval_metrics: dict[str, float] = field(default_factory=dict)

    @property
    def has_production_model(self) -> bool:
        return self.production_version is not None


def get_health_snapshot(registry: ModelRegistry, *, alias: str) -> HealthSnapshot:
    current = registry.get_by_alias(alias)
    if current is None:
        return HealthSnapshot(
            model_name=registry.model_name,
            alias=alias,
            production_version=None,
            last_trained_at=None,
        )

    run = registry.client.get_run(current.run_id)
    last_trained_at = (
        datetime.fromtimestamp(run.info.start_time / 1000, tz=timezone.utc)
        if run.info.start_time
        else None
    )
    return HealthSnapshot(
        model_name=registry.model_name,
        alias=alias,
        production_version=current.version,
        last_trained_at=last_trained_at,
        last_eval_metrics=dict(run.data.metrics),
    )


__all__ = ["HealthSnapshot", "get_health_snapshot"]
