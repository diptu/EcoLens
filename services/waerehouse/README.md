# Warehouse Micro-Service
Here is an implementation task list focused specifically on the Event-Driven Warehousing Service and its direct integrations with DuckDB, RabbitMQ, PostgreSQL (NeonDB), and dbt.

## Phase 1: Core Service Setup & Infrastructure Foundation
[ ] Project Structure & Environment: Initialize the warehouse microservice repository with a modular directory layout (consumers/, loaders/, dbt/, retention/, config/), configuring dependency management and environment variable management.

[ ] Database Connection Pools: Establish resilient connection managers for both DuckDB (local staging path) and NeonDB PostgreSQL (serverless connection pooling via psycopg or SQLAlchemy).

[ ] RabbitMQ Consumer Framework: Implement a robust asynchronous RabbitMQ consumer configured with automatic reconnections, dead-letter exchanges (DLX), and manual acknowledgment handling.

## Phase 2: Staging & Bounded Raw Ingestion Pipeline (raw.* Schema)
[ ] PostgreSQL Schema Provisioning: Define the raw schema in PostgreSQL, ensuring table designs include proper timestamp partitioning or indexing to optimize range-based deletions.

[ ] DuckDB-to-PostgreSQL Transfer Logic: Build the bulk-transfer extraction pipeline that reads newly staged records from DuckDB upon receiving a RabbitMQ trigger.

[ ] Idempotent Load Handling: Implement deduplication and upsert mechanisms in the raw layer using natural keys and payload hashes.

## Phase 3: Rolling-Window Retention & Storage Enforcement (Critical for Free Tier)
[ ] Automated Data Pruning Job (pg_cron or Celery Task): Implement a daily automated cleanup script that safely deletes raw and curated records older than 60 days (e.g., DELETE FROM raw.telemetry WHERE timestamp < NOW() - INTERVAL '2 months').

[ ] Vacuum & Bloat Management: Schedule routine VACUUM ANALYZE commands on PostgreSQL tables to reclaim disk space immediately after large chunks of historical data are purged, preventing dead tuples from exhausting the 0.5 GB limit.

[ ] Database Size Monitoring & Alerting: Build a lightweight monitoring query that tracks total database size against the 500 MB limit, triggering high-priority alerts or emergency pruning if storage crosses 80%.

[ ] Cloudflare R2 Cold-Storage Export: Before pruning data past the 2-month mark from NeonDB, configure a routine to dump compressed historical partitions (Parquet/CSV) directly to Cloudflare R2 for long-term cold storage and auditing compliance without bloating Postgres.

## Phase 4: Transformation Engine Integration (dbt)
[ ] dbt Project Initialization: Set up the integrated dbt project structure pointing directly to the NeonDB PostgreSQL instance.

[ ] Source Declarations (sources.yml): Define dbt source configurations targeting the raw.* tables with strict freshness tests.

[ ] Incremental dbt Models (stg_*, fct_*): Configure dbt models using incremental strategies where applicable, restricting builds and refreshes to process only the active 2-month window to minimize compute and storage overhead.

[ ] Data Quality Testing: Implement built-in dbt tests (not_null, unique, accepted_values) to safeguard against upstream data corruption.

## Phase 5: API Exposure, Monitoring & CI/CD
[ ] Internal REST Endpoints: Expose lightweight endpoints (e.g., FastAPI) for downstream services to query pipeline health and current storage utilization metrics.

[ ] Health & Readiness Probes: Implement standard /healthz and /readyz endpoints verifying active connections and free storage headrooms.

[ ] Pipeline Monitoring & Alerting: Configure metrics collection for queue latency, failed consumer events, dbt test failures, and database storage consumption trends.

[ ] CI/CD Pipeline Integration: Set up GitHub Actions workflows to automatically lint code, execute dbt test runs against an ephemeral test database, and deploy updates upon merge.