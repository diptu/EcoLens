# ecoLens — DuckDB Ingestion Pipeline

The ingestion pipeline is **Part 1 of the ecoLens three-layer architecture**:

```text
External APIs → DuckDB → PostgreSQL raw.* → dbt
```

(This used to be `External APIs → MongoDB → PostgreSQL raw.* → dbt` — MongoDB
has been removed entirely; see TODO.md's ECO-159 for the migration record.)

## Why DuckDB?

| Storage                | Purpose                                      |
| ---------------------- | --------------------------------------------- |
| **DuckDB**              | Raw, typed, per-source local file store       |
| **PostgreSQL `raw.*`** | Structured data consumed by dbt               |

> **DuckDB = raw source of truth. PostgreSQL `raw.*` = structured transformation input.**

Unlike the MongoDB it replaced, DuckDB is an embedded, zero-ops, single-file
store — no server process, no cluster to provision or pay for. The tradeoff
is DuckDB allows exactly **one read-write connection to the file at a time**;
`ingestion/storage/duckdb_store.py`'s `_connect_with_retry` absorbs
transient lock conflicts (e.g. two fetchers writing at once, or someone with
an interactive `duckdb` session left open) with backoff+jitter rather than
failing on the first attempt, but a long-held external connection can still
make a write wait or eventually fail — see `scripts/check_duckdb_status.py`
for diagnosing that.

---

## DuckDB Tables

One table per source, in the file at `Settings.historical_duckdb_path`
(default `data/historical/ecolens_historical.duckdb`, resolved to an
absolute path regardless of the calling process's cwd):

```text
ecolens_historical.duckdb
├── openelectricity_responses  # OE network, emissions, intensity
├── aemo_nem_dispatch          # NEM 5-minute dispatch
├── aemo_wem_dispatch          # WEM 30-minute data
├── bom_observations           # BoM weather observations
└── aemo_holidays              # Regional holiday snapshots
```

### Unique keys (`IngestionSettings.unique_key_for_source`)

| Source            | Table                        | Unique Key           |
| ------------------ | ----------------------------- | --------------------- |
| `openelectricity`  | `openelectricity_responses`  | `network_code + ts`   |
| `aemo_nem`         | `aemo_nem_dispatch`          | `region + ts`         |
| `aemo_wem`         | `aemo_wem_dispatch`          | `ts`                  |
| `bom`              | `bom_observations`           | `station_id + ts`     |
| `aemo_holidays`    | `aemo_holidays`              | `region + date`       |

Every table also carries:

```text
ts (or date, for holidays)
ingest_run_id
fetched_at
source
```

stamped by `duckdb_store.write_historical()` itself (mutating each doc in
place before writing) — every caller gets this bookkeeping "for free" the
same way MongoDB's old `bulk_upsert` used to provide it as a side effect.

---

## Pipeline

```text
External API
     │
     ▼
┌───────────────────────────────┐
│ fetch → validate → write      │
│                                │
│ 1. Fetch via httpx             │
│ 2. Retry + exponential backoff │
│ 3. Redis circuit breaker       │
│ 4. Validate with pandera       │
│ 5. duckdb_store.write_historical│
└──────────────┬─────────────────┘
               ▼
       ecolens_historical.duckdb
```

Each source runs concurrently (fetch side — HTTP calls, not the DuckDB
write itself, which is serialized by the single-writer-lock retry
mentioned above). Within a source, regions and stations are processed
concurrently using `asyncio.TaskGroup`.

---

## DuckDB Upsert

```python
# ecolens.ingestion.storage.duckdb_store.write_historical
def write_historical(
    source: str,
    docs: list[dict],
    *,
    run_id: str | None = None,
) -> int:
    if not docs:
        return 0

    run_id = run_id or uuid.uuid4().hex
    fetched_at = datetime.now(timezone.utc)
    for doc in docs:
        doc["ingest_run_id"] = run_id
        doc["fetched_at"] = fetched_at
        doc["source"] = source

    table = settings.table_for_source(source)
    key_columns = settings.unique_key_for_source(source)
    # INSERT ... ON CONFLICT (key_columns) DO UPDATE SET ... -- see
    # duckdb_store.py's _upsert() for the real SQL construction.
    ...
    return len(docs)
```

---

## DuckDB → PostgreSQL Syncer

The syncer (`ecolens.ingestion.storage.postgres.RawSyncer`) converts raw
DuckDB rows into structured PostgreSQL `raw.*` tables.

```python
async def sync_one(self, source: str, *, since: datetime | None = None) -> int:
    columns = _SOURCE_COLUMNS[source]
    table = f"raw.{self.ingestion_settings.table_for_source(source)}"

    # DuckDB has no async driver -- read in a thread so it doesn't
    # block the event loop the rest of this class's Postgres I/O runs on.
    rows = await asyncio.to_thread(
        duckdb_store.read_historical_since, source, since=since
    )

    sql = _upsert_sql(table, columns, unique_key)
    for batch in _chunks(rows, _PG_WRITE_CHUNK_SIZE):
        await self._write_batch(sql, batch)

    return len(rows)
```

```text
DuckDB Raw Rows
          │
          ▼
   Column projection
          │
          ▼
PostgreSQL raw.*
          │
          ▼
          dbt
```

---

## Verification

```bash
# Ingest external API data -> DuckDB (via the control API)
curl -X POST "localhost:8001/ingestion/historical?source=bom&date=2026-01-01"

# Verify DuckDB directly
uv run --active ./scripts/check_duckdb_status.py
# or: duckdb data/historical/ecolens_historical.duckdb -readonly -c "SELECT * FROM bom_observations LIMIT 1"

# Sync DuckDB -> PostgreSQL raw.*
uv run --active ./scripts/sync_raw.py

# Verify PostgreSQL
psql -U ecolens -d ecolens -c \
"SELECT count(*) FROM raw.bom_observations;"
```

---

## Backups

DuckDB is the *sole* raw store — there is no remote redundant copy the
way MongoDB Atlas used to provide. The local `.duckdb` file is a single
point of failure (disk loss, accidental `rm`, corruption), so back it
up:

```bash
# Snapshot (read-only EXPORT DATABASE -> timestamped Parquet dir, keeps
# the 14 most recent by default)
uv run --active ./scripts/backup_duckdb.py
# or: make backup-duckdb [KEEP=30]

# List / restore
uv run --active ./scripts/restore_duckdb.py --list
uv run --active ./scripts/restore_duckdb.py --latest --target /path/to/restored.duckdb
# or: make restore-duckdb SNAPSHOT=20260724T120000Z [TARGET=...] | make restore-duckdb LIST=1
```

The snapshot connection is read-only, but still subject to DuckDB's
single-writer file lock (a read-only open blocks while any read-write
connection is active elsewhere) — it retries with the same backoff
`duckdb_store._connect_with_retry` uses, rather than failing on the
first transient conflict. Not yet wired to a schedule; run manually or
via cron for now (root TODO.md ECO-161 tracks doing the same for the
CI ingest workflow, whose DuckDB file is otherwise ephemeral per run).

---

## Design Benefits

* **Idempotent** — Unique keys prevent duplicate records during retries.
* **Traceable** — `ingest_run_id` links records to ingestion executions.
* **Replayable** — Raw API responses remain in DuckDB and can be reprocessed without refetching the API.
* **Zero-ops** — No server process, no cluster; a single portable file.
* **Analytics-ready** — Queryable directly (via the `duckdb` CLI, a notebook, or `duckdb_store.read_historical`) without needing PostgreSQL at all, *and* PostgreSQL `raw.*` provides structured input for dbt.

> **DuckDB preserves the raw truth. PostgreSQL structures the truth. dbt transforms the truth.**
