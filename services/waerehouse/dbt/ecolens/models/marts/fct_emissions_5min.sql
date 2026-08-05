-- Row-level carbon intensity + emissions, one row per (ts, network_code,
-- region) at OpenElectricity's own reporting cadence (5-min NEM, 30-min
-- WEM — the "5min" in this mart's name is NEM's cadence and the name
-- README documents; WEM rows land here too at their own 30-min cadence,
-- not literally every 5 minutes). Table-materialized (dbt_project.yml).

select * from {{ ref('int_carbon_intensity') }}
