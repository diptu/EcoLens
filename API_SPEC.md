# ingestion endpoints
GET    /v1/data-sources                         List all sources
GET    /v1/data-sources/{id}                    Get one
PATCH  /v1/data-sources/{id}                    Edit cron / enable
POST   /v1/data-sources/{id}/run                Trigger fetch now
POST   /v1/data-sources/{id}/backfill          Backfill date range
GET    /v1/data-sources/{id}/health             Live health
GET    /v1/data-sources/{id}/history            Run history
GET    /v1/ingestion/pipelines                  List 8 pipelines
GET    /v1/ingestion/runs                       List recent runs
GET    /v1/ingestion/runs/{id}                  Get one run
GET    /v1/ingestion/failed                     Failed jobs
GET    /v1/ingestion/retry-queue                Retry queue
GET    /v1/ingestion/scheduler                  Prefect status
POST   /v1/ingestion/{id}/pause                 Pause a pipeline
POST   /v1/ingestion/{id}/resume                Resume a pipeline

# warehouse endpoints

GET    /v1/warehouse/tables                     List all warehouse tables (raw/stg/int/mart)

GET    /v1/warehouse/tables/{name}/schema       Get schema for one table (columns, types, indexes)

POST   /v1/warehouse/query                      Run read-only SQL (10K row cap, no DDL/DML)

GET    /v1/warehouse/runs                       List dbt run history (filter by status, selective, time)

POST   /v1/warehouse/run                        Trigger a dbt run (full or selective models, async)


# forecasting endpoints

# Core forecasting
POST   /v1/forecast/quantiles                    Main prediction (P10/P50/P90 for region + horizon)

GET    /v1/forecast/regions                      List supported regions (NEM, NSW1, QLD1, VIC1, SA1, TAS1, WEM)

GET    /v1/forecast/latest                       Latest forecasts across all regions

GET    /v1/forecast/horizon/{h}                  Forecast at a specific horizon (4h, 24h, 7d, 30d)

GET    /v1/forecast/{region}                     Forecast for a specific region

# Forecast admin
POST   /v1/forecast/retrain                      Trigger a manual retrain (LSTM + TFT + TimesFM)

GET    /v1/forecast/models                       List all models in MLflow registry

POST   /v1/forecast/models/{id}/promote          Promote a model version to production

POST   /v1/forecast/models/{id}/archive          Archive a model version

GET    /v1/forecast/accuracy                     Forecast accuracy metrics (MAPE, P10/P50/P90 coverage)

# Emissions & footprint
POST   /v1/emissions/calculate                   Calculate GHG emissions (Scope 1+2+3) for activity data

GET    /v1/emissions/factors                     List 14 emission factors (IPCC AR5 + AEMO NGES)

GET    /v1/emissions/intensity                   Current grid carbon intensity (gCO₂e/kWh) per region

POST   /v1/footprint                             Comprehensive footprint (forecast + carbon + intensity + emissions)

GET    /v1/footprint/snapshot                    Last 24h footprint snapshot

GET    /v1/footprint/trend?days=N                Footprint trend over N days (with P10-P90 band)

GET    /v1/footprint/by-source                   Footprint broken down by source (Grid, Gas, Diesel, ...)

GET    /v1/footprint/intensity                   Carbon intensity time series

# Renewable
GET    /v1/renewable/share                       Current renewable share (% wind+solar+hydro)

GET    /v1/renewable/mix                         Generation mix by source (coal, gas, wind, solar, hydro, biomass)

# Calibration
GET    /v1/calibration                           Conformal calibration model status (last retrain, coverage)

POST   /v1/calibration/retrain                   Retrain the conformal calibration model

# Operational
GET    /healthz                                  Liveness probe

GET    /readyz                                   Readiness probe (MLflow + Postgres + Redis + model loaded?)