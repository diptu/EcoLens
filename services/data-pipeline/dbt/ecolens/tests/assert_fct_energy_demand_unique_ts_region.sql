-- Singular test: fails if it returns any rows. fct_energy_demand unions
-- NEM + WEM demand (int_demand_with_weather) -- NEM's 5 regions and
-- WEM's single region are disjoint today, so (ts, region) should always
-- be unique, but that's an invariant about the region *values*, not
-- something a database constraint enforces the way raw.*'s PKs do (this
-- mart isn't a 1:1 copy of a single raw table). Catches it if a future
-- region ever collides between the two networks.

select ts, region, count(*) as row_count
from {{ ref('fct_energy_demand') }}
group by ts, region
having count(*) > 1
