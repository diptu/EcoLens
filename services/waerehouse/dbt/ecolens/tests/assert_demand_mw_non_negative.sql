-- Singular test: fails if it returns any rows. `demand_mw` is real grid
-- load in MW -- physically it can go slightly negative for a real
-- reason (net exporting regions/intervals can report a small negative
-- net demand in some AEMO feeds), but a large negative value is a data
-- quality bug (unit error, sign flip, a bad upstream join), not a real
-- grid event. -100 MW is a generous floor -- comfortably below any
-- genuine small-net-export reading this platform's regions have ever
-- shown, tight enough to still catch a real sign-flip bug (which
-- produces a magnitude-matching negative of a multi-thousand-MW demand
-- figure, not a small one).

select ts, region, demand_mw
from {{ ref('fct_energy_demand') }}
where demand_mw is not null
  and demand_mw < -100
