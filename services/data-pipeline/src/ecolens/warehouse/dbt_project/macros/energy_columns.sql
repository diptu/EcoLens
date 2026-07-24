{#
  Shared column contract for the three energy sources (AEMO NEM, AEMO
  WEM, OpenElectricity) -- all three emit the same 34-column v1.0
  schema (aemo_nem/schema.py and aemo_wem/schema.py both re-export
  openelectricity/schema.py's OUTPUT_COLUMNS). Centralised here so the
  staging models and the 30-min rollup in int_energy_unified_30min
  don't hand-transcribe ~25 metric names three times over.
#}

{% macro stg_energy_columns() %}
    ts::timestamptz as ts,
    region,
    network_code,
    lower(data_quality_status) as data_quality_status,
    schema_version,
    demand_mw::double precision as demand_mw,
    price_mwh::double precision as price_mwh,
    market_value::double precision as market_value,
    coal_black_mw::double precision as coal_black_mw,
    coal_brown_mw::double precision as coal_brown_mw,
    gas_ccgt_mw::double precision as gas_ccgt_mw,
    gas_ocgt_mw::double precision as gas_ocgt_mw,
    gas_other_mw::double precision as gas_other_mw,
    hydro_mw::double precision as hydro_mw,
    pumped_hydro_mw::double precision as pumped_hydro_mw,
    wind_mw::double precision as wind_mw,
    solar_utility_mw::double precision as solar_utility_mw,
    solar_rooftop_mw::double precision as solar_rooftop_mw,
    biomass_mw::double precision as biomass_mw,
    distillate_mw::double precision as distillate_mw,
    battery_discharge_mw::double precision as battery_discharge_mw,
    battery_charge_mw::double precision as battery_charge_mw,
    curtailment_solar_utility_mw::double precision as curtailment_solar_utility_mw,
    curtailment_wind_mw::double precision as curtailment_wind_mw,
    total_generation_mw::double precision as total_generation_mw,
    renewable_proportion::double precision as renewable_proportion,
    emissions_intensity_kgco2e_per_mwh::double precision as emissions_intensity_kgco2e_per_mwh,
    interconnector_imports_mw::double precision as interconnector_imports_mw,
    interconnector_exports_mw::double precision as interconnector_exports_mw,
    net_import_mw::double precision as net_import_mw,
    source,
    ingest_run_id,
    fetched_at::timestamptz as fetched_at
{% endmacro %}

{#
  The metric columns that get averaged when rolling 5-min NEM data (and
  re-aggregating already-30-min WEM data) up to the unified 30-min
  grain. Returned as a plain list so callers can Jinja-loop `avg(col)`.
#}
{% macro energy_metric_columns() %}
{{ return([
    "demand_mw", "price_mwh", "market_value",
    "coal_black_mw", "coal_brown_mw", "gas_ccgt_mw", "gas_ocgt_mw", "gas_other_mw",
    "hydro_mw", "pumped_hydro_mw", "wind_mw", "solar_utility_mw", "solar_rooftop_mw",
    "biomass_mw", "distillate_mw", "battery_discharge_mw", "battery_charge_mw",
    "curtailment_solar_utility_mw", "curtailment_wind_mw", "total_generation_mw",
    "renewable_proportion", "emissions_intensity_kgco2e_per_mwh",
    "interconnector_imports_mw", "interconnector_exports_mw", "net_import_mw"
]) }}
{% endmacro %}

{#
  The 10 BoM weather columns averaged onto the 30-min grid in
  int_energy_with_weather. Centralised for the same reason as
  energy_metric_columns() -- int_energy_filled_30min needs this exact
  list twice (once to build the gap-fill "island" ids, once to apply
  the fill), and ml_features_demand_v1 needs it to know what to select.
#}
{% macro weather_metric_columns() %}
{{ return([
    "temp_c", "apparent_temp_c", "dew_point_c", "humidity_pct",
    "wind_speed_kmh", "wind_direction_deg", "wind_gust_kmh",
    "pressure_hpa", "rain_since_9am_mm", "cloud_cover_pct"
]) }}
{% endmacro %}

{#
  Every numeric column that int_energy_filled_30min gap-fills: the
  energy metrics plus the weather metrics. One list so the fill logic
  and the "did I fill everything" review only has one place to look.
#}
{% macro ml_fill_columns() %}
{{ return(energy_metric_columns() + weather_metric_columns()) }}
{% endmacro %}
