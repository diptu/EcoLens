# ecoLens — MongoDB Ingestion Pipeline

The ingestion pipeline is **Part 1 of the ecoLens three-layer architecture**:

```text
External APIs → MongoDB → PostgreSQL raw.* → dbt
```

## Why MongoDB?

| Storage                | Purpose                                      |
| ---------------------- | -------------------------------------------- |
| **MongoDB**            | Raw, semi-structured, evolving API responses |
| **PostgreSQL `raw.*`** | Structured data consumed by dbt              |

> **MongoDB = raw source of truth. PostgreSQL `raw.*` = structured transformation input.**

---

## MongoDB Collections

```text
ecoLens
├── openelectricity_responses  # OE network, emissions, intensity
├── aemo_nem_dispatch          # NEM 5-minute dispatch
├── aemo_wem_dispatch          # WEM 30-minute data
├── bom_observations            # BoM weather observations
├── aemo_holidays               # Regional holiday snapshots
└── meta_ingest_runs            # Ingestion audit logs
```

### Unique Indexes

| Collection                  | Unique Key          |
| --------------------------- | ------------------- |
| `openelectricity_responses` | `network_code + ts` |
| `aemo_nem_dispatch`         | `region + ts`       |
| `aemo_wem_dispatch`         | `ts`                |
| `bom_observations`          | `station_id + ts`   |
| `aemo_holidays`             | `region + date`     |

All data collections also include:

```text
ts
ingest_run_id
fetched_at
source
```

---

## Pipeline

```text
External API
     │
     ▼
┌─────────────────────────────┐
│ MongoIngestionPipeline      │
│                             │
│ 1. Fetch via httpx          │
│ 2. Retry + exponential backoff│
│ 3. Redis circuit breaker    │
│ 4. Validate with pandera    │
│ 5. Bulk upsert to MongoDB   │
│ 6. Log ingestion run        │
└──────────────┬──────────────┘
               ▼
            MongoDB
```

Each source runs concurrently. Within a source, regions and stations are processed concurrently using `asyncio.TaskGroup`.

---

## MongoDB Upsert

```python
async def _upsert(
    self,
    source: Source,
    docs: list[dict],
    run_id: str,
) -> int:
    if not docs:
        return 0

    for doc in docs:
        doc.update(
            ingest_run_id=run_id,
            fetched_at=datetime.now(timezone.utc),
            source=source.name,
        )

    operations = [
        UpdateOne(
            {key: doc[key] for key in source.unique_key},
            {"$set": doc},
            upsert=True,
        )
        for doc in docs
    ]

    result = await self.db[source.collection].bulk_write(
        operations,
        ordered=False,
    )

    return result.upserted_count + result.modified_count
```

---

## MongoDB → PostgreSQL Syncer

The syncer converts raw MongoDB documents into structured PostgreSQL `raw.*` tables.

```python
async def sync_one(
    self,
    collection: str,
    table: str,
    flatten: Callable,
) -> int:

    cursor = self.mongo_db[collection].find({})
    rows = []

    async for doc in cursor:
        rows.extend(flatten(doc))

    if not rows:
        return 0

    df = pd.DataFrame(rows)

    async with self.pg_session() as session:
        await load_to_postgres(
            session,
            df,
            table,
            schema="raw",
        )

    return len(rows)
```

```text
MongoDB Raw Documents
          │
          ▼
       Flatten
          │
          ▼
      DataFrame
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
# Ingest external API data → MongoDB
curl -X POST localhost:8001/v1/ingest/bom

# Verify MongoDB
docker compose exec mongo mongosh ecolens --eval \
'db.bom_observations.find().limit(1)'

# Sync MongoDB → PostgreSQL raw.*
curl -X POST localhost:8001/v1/ingest/sync

# Verify PostgreSQL
psql -U ecolens -d ecolens -c \
"SELECT count(*) FROM raw.bom_observations;"
```

---

## Design Benefits

* **Idempotent** — Unique keys prevent duplicate records during retries.
* **Traceable** — `ingest_run_id` links records to ingestion executions.
* **Replayable** — Raw API responses remain in MongoDB and can be reprocessed without refetching the API.
* **Flexible** — MongoDB accommodates evolving external API schemas.
* **Analytics-ready** — PostgreSQL `raw.*` provides structured input for dbt.

> **MongoDB preserves the raw truth. PostgreSQL structures the truth. dbt transforms the truth.**
