"""Static catalog backing `GET /v1/ingestion/pipelines` (API_SPECEFICATIONS.md §2.1).

`API_SPECEFICATIONS.md`'s own §2.1 table lists **8** pipelines — 7 extract
+ 1 transform — across sources this codebase doesn't have (`open-meteo`,
`carbon`, `eia`, `custom-meters`) and stages this codebase doesn't run as
separate scheduled units (`anomaly`, `retrain` — anomaly detection runs
inline inside `pipeline.anomaly` on every fetch, not as its own pipeline;
there's no retrain pipeline because there's no trained model yet, see
`TODO.md`'s Forecasting section). Rather than invent 4 pipelines around
sources/credentials that don't exist, this catalog has **6**: one per real
ingest source in `app.service.pipeline.tasks.registry.SOURCES` (`extract`
stage) plus one for the dbt warehouse build (`transform` stage).

`pipe-dbt-warehouse`'s `cron` is the spec's own suggested value
(`*/15 * * * *`) but is **aspirational, not deployed** — there is no
GitHub Actions workflow (or any other scheduler) that actually runs `dbt
build` on a cadence; `POST /v1/dbt/build` / `ecolens-pipeline dbt build`
are manual-trigger-only today. `next_run_at` for this pipeline in the API
response is therefore a "if this cron were wired up" projection, not a
promise something will actually run then — same honesty caveat
`datasources.service`'s `PATCH .../schedule.cron` docstring already
carries for the 5 extract pipelines (editing a source's cron via the API
doesn't touch the real `.github/workflows/ingest-*.yml` cron either).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models.datasources import CATALOG_BY_ID

Stage = Literal["extract", "transform"]


@dataclass(frozen=True)
class PipelineDef:
    id: str
    name: str
    stage: Stage
    source_id: str | None  # app.models.datasources.DataSourceDef.id, extract only
    registry_key: (
        str | None
    )  # app.service.pipeline.tasks.registry.SOURCES key, extract only
    cron: str
    timezone: str
    depends_on: tuple[str, ...]


def _extract(pipeline_id: str, name: str, source_id: str) -> PipelineDef:
    entry = CATALOG_BY_ID[source_id]
    return PipelineDef(
        id=pipeline_id,
        name=name,
        stage="extract",
        source_id=source_id,
        registry_key=entry.registry_key,
        cron=entry.cron,
        timezone=entry.timezone,
        depends_on=(),
    )


_EXTRACT_PIPELINES = (
    _extract("pipe-oe", "OpenElectricity Ingest", "ds-oe"),
    _extract("pipe-aemo-nem", "AEMO NEM Ingest", "ds-aemo-nem"),
    _extract("pipe-aemo-wem", "AEMO WEM Ingest", "ds-aemo-wem"),
    _extract("pipe-bom", "Bureau of Meteorology Ingest", "ds-bom"),
    _extract("pipe-holidays", "AEMO Public Holidays Ingest", "ds-holidays"),
)

PIPELINES: tuple[PipelineDef, ...] = (
    *_EXTRACT_PIPELINES,
    PipelineDef(
        id="pipe-dbt-warehouse",
        name="dbt Warehouse Build",
        stage="transform",
        source_id=None,
        registry_key=None,
        cron="*/15 * * * *",
        timezone="UTC",
        depends_on=tuple(p.id for p in _EXTRACT_PIPELINES),
    ),
)

PIPELINES_BY_ID: dict[str, PipelineDef] = {p.id: p for p in PIPELINES}

# The one pause/resume rule API_SPECEFICATIONS.md §2.7 states explicitly
# ("Cannot pause pipe-dbt-warehouse — it's the only transform pipeline").
UNPAUSABLE_PIPELINE_ID = "pipe-dbt-warehouse"
