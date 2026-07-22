"""ecoLens warehouse API — entry point.

Read-only API over the PostgreSQL data warehouse produced by dbt.
Powers the dashboard (Next.js) and the forecast-api (PyTorch)
services. Never queries MongoDB.

Architecture
============
    ┌──────────────┐  ┌──────────────┐
    │  dashboard   │  │ forecast-api │
    └──────┬───────┘  └──────┬───────┘
           │                 │
           │   HTTP/JSON     │
           └────────┬────────┘
                    │
            ┌───────▼───────┐
            │ warehouse/api │  ← this package (FastAPI :8002)
            └───────┬───────┘
                    │ asyncpg
            ┌───────▼───────┐
            │  PostgreSQL   │  ← populated by dbt (mongo → pg)
            │  warehouse    │
            └───────────────┘

Why a separate service?
=======================
The data-pipeline service handles WRITE paths (fetchers, dbt, MLflow).
The warehouse-api handles READ paths (queries, aggregations, joins).
Splitting read/write:
  - Lets the dashboard and forecast-api hit a stable, query-optimized
    surface (vs raw dbt models that change shape)
  - Lets us cache hot queries (Cache/cache.py, short TTL) without
    touching the writers
  - Lets us rate-limit and auth (dependencies.require_api_key)
    separately from the ingestion API

Split by concern (unlike the original single-file draft):
  settings.py       WarehouseApiSettings — pg/redis/api tuning, own env prefix
  db.py             ConnectionPool — asyncpg wrapper + health check
  cache.py          Cache — async Redis cache, no-ops when unconfigured
  models.py         Pydantic response models
  validation.py     pure region/range/year validators
  queries.py        one async query function per warehouse table
  dependencies.py   FastAPI Depends wrappers (pool/settings come from app.state)
  routes.py         health_router (no auth) + data_router (API-key gated)
  app.py            create_app() factory + lifespan (connects pool/cache)
  api.py            this file — builds and exposes the module-level `app`

Routes
======
    GET  /health
    GET  /regions
    GET  /regions/{region}/demand
    GET  /regions/{region}/generation
    GET  /regions/{region}/weather
    GET  /regions/{region}/summary
    GET  /national/demand
    GET  /features/demand/v1
    GET  /features/demand/v1/latest
    GET  /holidays/{year}

Usage
=====
    uvicorn ecolens.warehouse.api.api:app --host 0.0.0.0 --port 8002
"""

from __future__ import annotations

from .app import create_app

app = create_app()

__all__ = ["app"]
