-- Singular test: int_energy_filled_30min must have exactly one row
-- every 30 minutes per region between that region's own min and max
-- ts_30 -- this is the whole point of the gap-filling step. Fails
-- (returns rows) if any region is missing a slot.

with bounds as (
    select
        region,
        min(ts_30) as min_ts_30,
        max(ts_30) as max_ts_30
    from {{ ref("int_energy_filled_30min") }}
    group by region
),

expected as (
    select
        b.region,
        gs.ts_30
    from bounds b
    cross join generate_series(b.min_ts_30, b.max_ts_30, interval '30 minutes') as gs (ts_30)
)

select expected.region, expected.ts_30
from expected
left join {{ ref("int_energy_filled_30min") }} actual
    on actual.region = expected.region
    and actual.ts_30 = expected.ts_30
where actual.ts_30 is null
