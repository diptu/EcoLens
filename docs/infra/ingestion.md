### Behind the Scenes: How EcoLens Builds a Trustworthy Energy Pipeline

When you look at a dashboard showing grid demand or carbon intensity, it’s easy to forget the complex journey behind every number. At **EcoLens**, our goal is simple: every data point on our dashboard must come from a verifiable, real-world source—never mock data.

Here is how our ingestion pipeline brings together data from multiple energy markets and weather services into a single source of truth.

---

### Where the Data Comes From

EcoLens ingests data across five primary sources:

* **AEMO NEM:** Five-minute interval dispatch data (demand, wholesale price, fuel mix) covering Australia’s eastern grid using AEST.
* **AEMO WEM:** Five-minute interval market data for Western Australia, operating under AWST.
* **OpenElectricity:** An independent third-party provider for fuel mix and carbon intensity, used alongside AEMO data to provide transparent, multi-perspective comparisons.
* **Bureau of Meteorology:** Hourly weather observations from six regional stations to feed weather-driven demand forecasting models.
* **Public Holiday Calendar:** Regional holiday schedules stored directly in code to help models detect non-standard consumption patterns.

---

### The Ingestion Workflow

To keep operational overhead low, a **Celery Beat job runs every 30 minutes**, triggering parallel ingestion tasks across all sources.

```
[ Data Source ]
      │
      ▼
┌───────────────────────────┐
│  1. Redis Circuit Breaker │  <-- Trips after 5 consecutive failures
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│  2. Local DuckDB Staging  │  <-- Appends raw data with run ID
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│  3. S3 Snapshot Upload    │  <-- Pushes run snapshot to MinIO / R2
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│  4. RabbitMQ Event        │  <-- Publishes completion message
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│  5. PostgreSQL Warehouse  │  <-- Idempotent bulk-load via natural keys
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│  6. dbt Transformation    │  <-- Cleans & builds final data marts
└─────────────┬─────────────┘
              │
              ▼
[ Dashboard & Forecasting API ]

```

---

### Key Architectural Decisions

* **Idempotent Data Ingestion:** Deduplication is built directly into the Postgres loading layer. Using natural keys (such as `timestamp` + `region`), duplicate reads from API retries, overlapping lookback windows, or backfills are ignored.

* **Separate Live & Historical Paths:** Live APIs often enforce rolling windows (e.g., the weather API only holds 72 hours of data). Historical backfills utilize dedicated archive paths like AEMO public archives and Open-Meteo reanalysis datasets.
* **Defined Data Lifecycles:** Raw Postgres records are retained for 60 days, while transformed `dbt` query marts retain 30 days locally before older data shifts to cold storage.
* **Complete Auditability:** Every run is recorded in `meta._ingest_log`, allowing any value on the final dashboard to be traced back to its raw ingestion run.


