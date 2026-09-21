### Behind the Scenes: How EcoLens Turns Raw Readings Into Trustworthy Data

Getting energy and weather data into PostgreSQL is only half the battle. A raw table filled with five-minute readings isn't immediately useful for forecasting models or dashboards.

Here is how **EcoLens** uses **dbt** (data build tool) to clean, join, reshape, and aggregate raw readings into analytics-ready datasets.

---

### The Three-Tier Warehouse Architecture

EcoLens processes data through three distinct layers using dbt to maintain clear boundaries between ingestion and consumption:

```
[ Ingestion Pipeline ]
         │
         ▼
┌─────────────────────────────────┐
│  raw.* (PostgreSQL)             │  <-- Ingested raw tables (AEMO, BOM, etc.)
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  1. Staging Layer (Views)       │  <-- Standardizes types & renames columns
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  2. Intermediate Layer          │  <-- Ephemeral logic (unpivoting, joining,
│     (Ephemeral)                 │      calculating fuel-weighted emissions)
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  3. Marts Layer (Tables)        │  <-- Analytics-ready datasets (fct_energy_demand,
└────────┬────────────────────────┘      fct_generation_mix, fct_carbon_intensity)
         │
         ▼
[ Forecasting API & Dashboard ]

```

---

### Key Architectural Decisions

* **Incremental Fact Marts:** Because raw data is purged after 60 days, fact marts (`fct_energy_demand`, `fct_generation_mix`, etc.) are built incrementally using a `delete+insert` strategy based on natural keys. This enables historical metrics to accumulate permanently, decoupled from the raw storage retention window.
* **Event-Driven, Locked Builds:** Builds are triggered by RabbitMQ ingestion messages rather than fixed schedules. To avoid redundant or overlapping runs, the pipeline enforces a **15-minute lock limit** via an internal log table. A successful build emits a `warehouse refreshed` event to trigger downstream forecasting model fine-tuning.
* **Cost-Conscious Archival Strategy:** Recent mart data stays in the primary database for rapid querying. Data older than 30 days is migrated to a secondary archive database in small, time-windowed batches to avoid connection pool timeouts.
* **Custom Domain Testing:** Beyond standard uniqueness and non-null constraints, dbt executes custom domain checks—such as validating that individual fuel-mix components sum to the reported total and flagging unrealistic negative demand spikes.

---

### Real-World Lessons: Two Technical Challenges Fixed

* **Connection Pool Dropouts on Bulk Archival:** An initial archival job attempted to move 400,000+ rows in a single long-lived connection, causing database connection poolers to drop the session after 5.5 minutes. The fix was batching archival runs into smaller time windows using fresh connections.
* **Bypassing Cross-Database FDW Latency:** Querying across primary and archive databases via `postgres_fdw` introduced 1.7 to 3 seconds of latency. EcoLens solved this by strictly separating real-time querying (primary DB) from historical storage (archive DB) rather than using a federated wrapper.

By isolating raw staging from final application marts, relying on incremental models, and executing strict domain tests, EcoLens ensures that raw energy inputs are converted into reliable, explainable metrics.