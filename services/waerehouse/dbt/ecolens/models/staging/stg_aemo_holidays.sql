-- Annual public-holiday calendar snapshot, per region. Thin passthrough
-- over raw.aemo_holidays (docs/data/ingestion-schema.md).

select
    date,
    region,
    holiday_name,
    is_workday,
    source,
    ingested_at,
    ingest_run_id
from {{ source('raw', 'aemo_holidays') }}
