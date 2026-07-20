#!/bin/bash

# Define the root structure
BASE="src/ecolens"

# Create Directories
mkdir -p "$BASE/ingestion/sources" "$BASE/ingestion/storage" "$BASE/ingestion/validators"
mkdir -p "$BASE/warehouse/dbt_project/seeds" "$BASE/warehouse/dbt_project/models"/{staging,intermediate,marts} "$BASE/warehouse/dbt_project/tests"
mkdir -p "$BASE/forecasting/models" "$BASE/forecasting/training" "$BASE/forecasting/evaluation" "$BASE/forecasting/mlops" "$BASE/forecasting/serving"
mkdir -p "$BASE/shared/db" "$BASE/shared/cache" "$BASE/shared/observability"
mkdir -p "$BASE/api/schemas"

# Create Files
# Ingestion
touch "$BASE/ingestion/__init__.py" "$BASE/ingestion/api.py" "$BASE/ingestion/circuit_breaker.py"
touch "$BASE/ingestion/sources/"{openelectricity.py,aemo_nem.py,aemo_wem.py,bom.py,holidays.py}
touch "$BASE/ingestion/storage/"{s3.py,mongo.py,postgres.py}
touch "$BASE/ingestion/validators/"{openelectricity.py,aemo.py,bom.py}

# Warehouse
touch "$BASE/warehouse/__init__.py" "$BASE/warehouse/api.py" "$BASE/warehouse/runner.py"
touch "$BASE/warehouse/dbt_project/dbt_project.yml"

# Forecasting
touch "$BASE/forecasting/__init__.py" "$BASE/forecasting/api.py" "$BASE/forecasting/data.py" "$BASE/forecasting/features.py"
touch "$BASE/forecasting/models/lstm.py"
touch "$BASE/forecasting/training/"{losses.py,train.py,tune.py,online.py}
touch "$BASE/forecasting/evaluation/"{metrics.py,conformal.py,evaluate.py}
touch "$BASE/forecasting/mlops/"{registry.py,promote.py,drift.py,health.py}
touch "$BASE/forecasting/serving/forecast.py"

# Shared
touch "$BASE/shared/__init__.py" "$BASE/shared/config.py"
touch "$BASE/shared/db/session.py"
touch "$BASE/shared/cache/redis_client.py"
touch "$BASE/shared/observability/"{logging.py,metrics.py}

# API & Root
touch "$BASE/api/__init__.py" "$BASE/api/app.py" "$BASE/api/deps.py"
touch "$BASE/cli.py"

echo "Project scaffolded successfully at $BASE"