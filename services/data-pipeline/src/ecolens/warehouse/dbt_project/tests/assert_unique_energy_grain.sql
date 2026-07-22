-- Singular test: (region, ts_30) must be unique in the unified energy
-- series. Fails (returns rows) if the NEM/WEM union produced a
-- duplicate grain key.

select region, ts_30, count(*) as n
from {{ ref("int_energy_unified_30min") }}
group by region, ts_30
having count(*) > 1
