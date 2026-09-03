# API Reference — data-pipeline 

| Service | `data-pipeline` |
|---|---|
| Tier | worker (called by dashboard BFF + other services) |
| Auth | JWT bearer (admin or analyst) |
| Format | JSON (UTF-8) |
| Versioning | URL path (`/v1`) — stable for 6 months, then 12 months deprecation |

This document covers the **first 19 endpoints** (Data Sources, Ingestion Pipelines, Data Quality). Other groups (Emissions, Forecast, Analytics, ML, Operational, System Health, Anomaly, Warehouse) are documented in `API_REFERENCE_DATA_PIPELINE_2.md`.

---

## Conventions

| Symbol | Meaning |
|---|---|
| ✅ required | Field must be present |
| ⚠️ optional | Field can be omitted |
| 🔒 admin only | Requires role `admin` (analyst gets 403) |
| `null` | Field is null when the feature isn't applicable (paused source, etc.) |
| `int \| null` | Field can be a number or null |
| ISO 8601 | UTC timestamps with `Z` suffix (`2024-06-01T10:00:00Z`) |
| `cursor` | Opaque pagination cursor (not user-parseable) |
| `If-Match` | Optimistic concurrency header (for PATCH) |

### Standard error envelope (all 4xx/5xx)

```json
{
  "error": {
    "code": "forbidden",
    "message": "Endpoint requires role: admin",
    "field": null,
    "request_id": "9f2c-4a13-bb71"
  }
}
```

| HTTP | Code | When |
|---|---|---|
| 400 | `invalid_query`, `invalid_body`, `invalid_path_param` | Bad request |
| 401 | `unauthorized` | Missing / invalid JWT |
| 403 | `forbidden` | Wrong role |
| 404 | `not_found` | Resource doesn't exist |
| 409 | `conflict` | Optimistic concurrency / state conflict |
| 422 | `unprocessable` | Schema validation failed |
| 429 | `rate_limited` | Too many requests |
| 500 | `internal` | Server error |
| 503 | `unavailable` | Upstream (Postgres/Redis/RabbitMQ) down |

---

# Section 1: Data Sources

## 1.1 `GET /v1/data-sources`

List all data sources. Powers the **Data Sources** admin page.

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 30s Redis (key: `datasources:list:v1:{query_hash}`) |
| Latency P95 | < 80 ms |
| Idempotent | ✅ |

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `category` | enum | — | `grid`, `weather`, `carbon`, `fuel`, `custom` |
| `enabled` | bool | — | `true` (only enabled), `false` (only disabled) |
| `health` | enum | — | `healthy`, `degraded`, `failing`, `paused` |
| `search` | string | — | Full-text search on name + description (max 64 chars) |
| `sort` | enum | `name` | `name`, `category`, `last_run_at`, `success_rate_pct` |
| `order` | enum | `asc` | `asc`, `desc` |
| `limit` | int | 50 | 1–200 |
| `cursor` | string | — | Opaque pagination cursor |

### Response 200

```json
{
  "meta": {
    "total": 9,
    "enabled_count": 8,
    "disabled_count": 1,
    "healthy_count": 8,
    "degraded_count": 1,
    "failing_count": 0,
    "paused_count": 0,
    "as_of": "2024-06-01T10:00:00.123Z",
    "next_refresh_at": "2024-06-01T10:00:30.123Z"
  },
  "data": [
    {
      "id": "ds-aemo-nem",
      "name": "AEMO NEM",
      "category": "grid",
      "description": "Australian Energy Market Operator — NEM (NSW1, QLD1, VIC1, SA1, TAS1) demand, price, generation, 30-min.",
      "url": "https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem",
      "license": "CC BY 4.0",
      "auth": { "type": "none" },
      "schedule": {
        "cron": "*/5 * * * *",
        "cadence": "Every 5 minutes",
        "timezone": "Australia/Sydney",
        "enabled": true,
        "next_run_at": "2024-06-01T10:05:00Z",
        "last_run_at": "2024-06-01T10:00:00Z"
      },
      "health": {
        "status": "healthy",
        "success_rate_pct_24h": 100.0,
        "success_rate_pct_7d":  99.8,
        "p50_duration_ms": 245,
        "p95_duration_ms": 612,
        "p99_duration_ms": 1100,
        "consecutive_failures": 0,
        "circuit_breaker": "closed",
        "last_check_at": "2024-06-01T10:00:01.234Z"
      },
      "last_run": {
        "id": "run-1730000000-abc12",
        "status": "success",
        "started_at": "2024-06-01T10:00:00Z",
        "finished_at": "2024-06-01T10:00:00.479Z",
        "duration_ms": 479,
        "records_fetched": 12,
        "records_inserted": 12,
        "duplicates_skipped": 0,
        "anomalies_flagged": 0,
        "error": null
      },
      "regions": ["NSW1", "QLD1", "VIC1", "SA1", "TAS1"],
      "metadata": { "data_card_id": "card-aemo-nem-2024-05", "schema_version": 3, "owner_team": "data-eng" },
      "version": 1,
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-05-20T14:30:00Z"
    }
    /* ...8 more sources... */
  ],
  "next_cursor": null,
  "has_more": false
}
```

> **Full 9-source sample response**: see `/workspace/API_DATA_SOURCES.md`

---

## 1.2 `GET /v1/data-sources/{id}` · `PATCH /v1/data-sources/{id}`

Get one source, or update its schedule / enable toggle.

| Aspect | Value |
|---|---|
| Auth (GET) | JWT — admin or analyst |
| Auth (PATCH) | 🔒 admin only |
| Cache (GET) | 30s Redis (key: `datasources:one:v1:{id}`) |
| Cache invalidation (PATCH) | Clears `datasources:list:v1:*` on success |
| Latency P95 | < 60 ms (GET), < 120 ms (PATCH) |
| Idempotent | ✅ (GET) / ⚠️ (PATCH with If-Match) |

### Path parameters

| Param | Type | Description |
|---|---|---|
| `id` | string | Source ID (e.g. `ds-aemo-nem`) |

### Headers (PATCH only)

| Header | Required | Description |
|---|---|---|
| `If-Match` | ⚠️ recommended | Current `version` int (returns 409 if mismatch) |

### Request body (PATCH)

```json
{
  "schedule": {
    "cron": "*/10 * * * *",
    "timezone": "Australia/Sydney",
    "enabled": true
  },
  "description": "Updated to clarify regional coverage"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `schedule.cron` | string | ⚠️ | 5-field cron; validated against regex `^(\*\|[0-9,\-\/]+)( [0-9,\-\/]+){4}$` |
| `schedule.timezone` | string | ⚠️ | IANA timezone |
| `schedule.enabled` | bool | ⚠️ | Toggle fetcher on/off |
| `description` | string | ⚠️ | New description (max 500 chars) |
| `auth` | object | ⚠️ | Update auth type (only `type` changeable; secret stays in env) |
| `metadata` | object | ⚠️ | Merge new keys (does NOT replace) |

### Response 200 (GET / PATCH)

```json
{
  "id": "ds-aemo-nem",
  "name": "AEMO NEM",
  "category": "grid",
  "description": "Australian Energy Market Operator — NEM (NSW1, QLD1, VIC1, SA1, TAS1) demand, price, generation, 30-min.",
  "url": "https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem",
  "license": "CC BY 4.0",
  "auth": { "type": "none" },
  "schedule": {
    "cron": "*/10 * * * *",
    "cadence": "Every 10 minutes",
    "timezone": "Australia/Sydney",
    "enabled": true,
    "next_run_at": "2024-06-01T10:10:00Z",
    "last_run_at": "2024-06-01T10:00:00Z"
  },
  "health": { /* ...same as before, eventually updated... */ },
  "last_run": { /* ... */ },
  "regions": ["NSW1", "QLD1", "VIC1", "SA1", "TAS1"],
  "metadata": { "data_card_id": "card-aemo-nem-2024-05", "schema_version": 3, "owner_team": "data-eng", "last_edited_by": "diptu" },
  "version": 2,
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-06-01T10:02:00Z"
}
```

### Errors

| Status | Code | When |
|---|---|---|
| 400 | `invalid_cron` | Cron regex mismatch |
| 400 | `invalid_timezone` | Not a valid IANA tz |
| 404 | `not_found` | No source with this id |
| 409 | `version_mismatch` | `If-Match` doesn't match current `version` |

---

## 1.3 `POST /v1/data-sources/{id}/run`

Trigger an immediate fetch (skip the cron schedule).

| Aspect | Value |
|---|---|
| Auth | 🔒 admin only |
| Latency P95 | < 200 ms (returns immediately, fetch runs in Prefect) |
| Idempotent | ✅ via `Idempotency-Key` header (TTL: 1 hour) |

### Path parameters

| Param | Type | Description |
|---|---|---|
| `id` | string | Source ID |

### Headers

| Header | Required | Description |
|---|---|---|
| `Idempotency-Key` | ⚠️ recommended | UUID — same key + same body returns cached 202 |
| `X-Reason` | ⚠️ | Free-text reason (logged for audit) |

### Request body

```json
{
  "force": false,
  "deduplicate": true
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `force` | bool | `false` | Bypass circuit breaker (if open) |
| `deduplicate` | bool | `true` | Skip records already present (sha256 match) |

### Response 202

```json
{
  "run_id": "run-1730000123-rst90",
  "source_id": "ds-aemo-nem",
  "status": "queued",
  "queued_at": "2024-06-01T10:02:03.000Z",
  "estimated_start_at": "2024-06-01T10:02:05.000Z",
  "priority": "high",
  "triggered_by": "diptu@ecolens.com",
  "reason": "Manual verification after cron change",
  "deduplicate": true,
  "force": false
}
```

### Errors

| Status | Code | When |
|---|---|---|
| 404 | `not_found` | No source with this id |
| 409 | `already_running` | A run for this source is already in progress |
| 503 | `circuit_open` | Circuit breaker is open and `force=false` |

---

## 1.4 `POST /v1/data-sources/{id}/backfill`

Fetch a date range (e.g. missed data due to outage).

| Aspect | Value |
|---|---|
| Auth | 🔒 admin only |
| Latency P95 | < 200 ms (returns 202, runs in Prefect) |
| Idempotent | ⚠️ via `Idempotency-Key` (TTL: 1 hour) |

### Path parameters

| Param | Type | Description |
|---|---|---|
| `id` | string | Source ID |

### Request body

```json
{
  "start": "2024-05-20T00:00:00Z",
  "end":   "2024-05-27T00:00:00Z",
  "chunk": "P1D",
  "concurrency": 2,
  "deduplicate": true
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `start` | ISO 8601 | ✅ | — | Backfill start (must be < `end`) |
| `end` | ISO 8601 | ✅ | — | Backfill end (must be > `start`, ≤ now) |
| `chunk` | ISO 8601 duration | ⚠️ | `P1D` | How to slice the range (`PT1H`, `P1D`, `P1W`) |
| `concurrency` | int | ⚠️ | `1` | Parallel fetches (1–4) |
| `deduplicate` | bool | ⚠️ | `true` | Skip records already present |

### Response 202

```json
{
  "backfill_id": "bf-1730000167-uvw12",
  "source_id": "ds-aemo-nem",
  "status": "queued",
  "queued_at": "2024-06-01T10:02:47.000Z",
  "start": "2024-05-20T00:00:00Z",
  "end":   "2024-05-27T00:00:00Z",
  "chunk": "P1D",
  "concurrency": 2,
  "deduplicate": true,
  "total_chunks": 7,
  "estimated_duration_seconds": 420,
  "triggered_by": "diptu@ecolens.com",
  "progress_url": "/v1/ingestion/runs?backfill_id=bf-1730000167-uvw12"
}
```

### Errors

| Status | Code | When |
|---|---|---|
| 400 | `invalid_range` | `start >= end` or `end > now` |
| 400 | `range_too_large` | > 90 days |
| 404 | `not_found` | No source with this id |
| 409 | `backfill_in_progress` | Another backfill for this source is running |

---

## 1.5 `GET /v1/data-sources/{id}/health`

Live health metrics for one source (higher resolution than the `health` field in `GET /v1/data-sources`).

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 10s Redis |
| Latency P95 | < 100 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "source_id": "ds-aemo-nem",
  "status": "healthy",
  "as_of": "2024-06-01T10:02:00.000Z",
  "success_rate_pct_1h": 100.0,
  "success_rate_pct_24h": 100.0,
  "success_rate_pct_7d":  99.8,
  "success_rate_pct_30d": 99.5,
  "p50_duration_ms": 245,
  "p95_duration_ms": 612,
  "p99_duration_ms": 1100,
  "consecutive_failures": 0,
  "circuit_breaker": {
    "state": "closed",
    "opened_at": null,
    "half_open_at": null,
    "recovery_seconds": 300
  },
  "last_5_runs": [
    { "id": "run-abc", "status": "success", "duration_ms": 245, "records": 12, "at": "2024-06-01T10:00:00Z" },
    { "id": "run-def", "status": "success", "duration_ms": 280, "records": 12, "at": "2024-06-01T09:55:00Z" },
    { "id": "run-ghi", "status": "success", "duration_ms": 612, "records": 12, "at": "2024-06-01T09:50:00Z" },
    { "id": "run-jkl", "status": "success", "duration_ms": 234, "records": 12, "at": "2024-06-01T09:45:00Z" },
    { "id": "run-mno", "status": "success", "duration_ms": 198, "records": 12, "at": "2024-06-01T09:40:00Z" }
  ],
  "errors_by_code_24h": {
    "missing_credentials": 0,
    "timeout": 0,
    "rate_limited": 0,
    "schema_mismatch": 0
  }
}
```

### Errors

| Status | Code | When |
|---|---|---|
| 404 | `not_found` | No source with this id |

---

## 1.6 `GET /v1/data-sources/{id}/history`

Historical run log for one source (paginated, most-recent first).

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 60s Redis |
| Latency P95 | < 200 ms |
| Idempotent | ✅ |

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `status` | enum | — | `success`, `failed`, `partial`, `running`, `queued` |
| `from` | ISO 8601 | — | Start of time window |
| `to` | ISO 8601 | — | End of time window |
| `limit` | int | 100 | 1–500 |
| `cursor` | string | — | Opaque cursor |

### Response 200

```json
{
  "source_id": "ds-aemo-nem",
  "total": 288,
  "data": [
    {
      "id": "run-1730000000-abc12",
      "status": "success",
      "started_at": "2024-06-01T10:00:00Z",
      "finished_at": "2024-06-01T10:00:00.479Z",
      "duration_ms": 479,
      "records_fetched": 12,
      "records_inserted": 12,
      "duplicates_skipped": 0,
      "anomalies_flagged": 0,
      "trigger": "schedule",
      "error": null
    },
    {
      "id": "run-1729999700-xyz99",
      "status": "success",
      "started_at": "2024-06-01T09:55:00Z",
      "finished_at": "2024-06-01T09:55:00.612Z",
      "duration_ms": 612,
      "records_fetched": 12,
      "records_inserted": 12,
      "duplicates_skipped": 0,
      "anomalies_flagged": 0,
      "trigger": "schedule",
      "error": null
    }
    /* ...up to `limit` runs... */
  ],
  "next_cursor": "eyJ0IjoxNzI5OTk5NjcwfQ",
  "has_more": true
}
```

### `trigger` values

| Value | Meaning |
|---|---|
| `schedule` | Fired by cron |
| `manual` | Triggered by `POST /v1/data-sources/{id}/run` |
| `backfill` | Part of a backfill chunk |
| `retry` | Retry from DLQ |
| `dependency` | Triggered by another source's success |

---

# Section 2: Ingestion Pipelines

## 2.1 `GET /v1/ingestion/pipelines`

List all 8 ingestion pipelines (the orchestration units — not the data sources themselves).

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 15s Redis |
| Latency P95 | < 100 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "meta": {
    "total": 8,
    "active": 7,
    "paused": 1,
    "as_of": "2024-06-01T10:00:00Z"
  },
  "data": [
    {
      "id": "pipe-aemo-nem",
      "name": "AEMO NEM Ingest",
      "source_id": "ds-aemo-nem",
      "stage": "extract",
      "status": "active",
      "schedule": {
        "cron": "*/5 * * * *",
        "timezone": "Australia/Sydney",
        "enabled": true
      },
      "last_run_at": "2024-06-01T10:00:00Z",
      "next_run_at": "2024-06-01T10:05:00Z",
      "run_count_24h": 288,
      "success_rate_24h": 100.0,
      "p95_duration_ms_24h": 612
    },
    {
      "id": "pipe-dbt-warehouse",
      "name": "dbt Warehouse Build",
      "stage": "transform",
      "status": "active",
      "schedule": {
        "cron": "*/15 * * * *",
        "timezone": "Australia/Sydney",
        "enabled": true
      },
      "depends_on": ["pipe-aemo-nem", "pipe-aemo-wem", "pipe-open-meteo", "pipe-bom", "pipe-carbon"],
      "last_run_at": "2024-06-01T09:45:00Z",
      "next_run_at": "2024-06-01T10:00:00Z",
      "run_count_24h": 96,
      "success_rate_24h": 100.0,
      "p95_duration_ms_24h": 8400
    }
    /* ...6 more... */
  ]
}
```

### The 8 pipelines

| ID | Stage | Schedule | Depends on |
|---|---|---|---|
| `pipe-aemo-nem` | extract | `*/5 * * * *` | — |
| `pipe-aemo-wem` | extract | `*/30 * * * *` | — |
| `pipe-open-meteo` | extract | `0 * * * *` | — |
| `pipe-bom` | extract | `*/30 * * * *` | — |
| `pipe-carbon` | extract | `0 * * * *` | — |
| `pipe-eia` | extract | `0 * * * *` | — |
| `pipe-custom-meters` | extract | `*/5 * * * *` | — |
| `pipe-dbt-warehouse` | transform | `*/15 * * * *` | all 7 extract pipelines |

### `stage` values

| Value | Meaning |
|---|---|
| `extract` | Pulls from external API → MongoDB staging |
| `transform` | dbt run on DuckDB → Postgres warehouse |
| `anomaly` | Anomaly detection (every 15 min) |
| `retrain` | Model retrain (every 6h, only if drift detected) |

---

## 2.2 `GET /v1/ingestion/runs`

List recent ingest runs (across all pipelines).

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 30s Redis |
| Latency P95 | < 200 ms |
| Idempotent | ✅ |

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `pipeline_id` | string | — | Filter to one pipeline |
| `source_id` | string | — | Filter to one source |
| `status` | enum | — | `success`, `failed`, `partial`, `running`, `queued`, `cancelled` |
| `trigger` | enum | — | `schedule`, `manual`, `backfill`, `retry`, `dependency` |
| `from` | ISO 8601 | — | Start of time window |
| `to` | ISO 8601 | — | End of time window |
| `limit` | int | 100 | 1–500 |
| `cursor` | string | — | Opaque cursor |

### Response 200

```json
{
  "meta": {
    "total": 1247,
    "filtered": 312
  },
  "data": [
    {
      "id": "run-1730000000-abc12",
      "pipeline_id": "pipe-aemo-nem",
      "source_id": "ds-aemo-nem",
      "status": "success",
      "trigger": "schedule",
      "started_at": "2024-06-01T10:00:00Z",
      "finished_at": "2024-06-01T10:00:00.479Z",
      "duration_ms": 479,
      "records_fetched": 12,
      "records_inserted": 12,
      "duplicates_skipped": 0,
      "anomalies_flagged": 0,
      "error": null,
      "metadata": { "prefect_flow_run_id": "abc-def-123" }
    }
  ],
  "next_cursor": "eyJ0IjoxNzI5OTk5NjcwfQ",
  "has_more": true
}
```

---

## 2.3 `GET /v1/ingestion/runs/{id}`

Get full details of one run (with logs, retry chain, lineage).

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | ❌ (always live) |
| Latency P95 | < 200 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "id": "run-1730000000-abc12",
  "pipeline_id": "pipe-aemo-nem",
  "source_id": "ds-aemo-nem",
  "status": "success",
  "trigger": "schedule",
  "started_at": "2024-06-01T10:00:00Z",
  "finished_at": "2024-06-01T10:00:00.479Z",
  "duration_ms": 479,
  "records_fetched": 12,
  "records_inserted": 12,
  "duplicates_skipped": 0,
  "anomalies_flagged": 0,
  "error": null,
  "metadata": {
    "prefect_flow_run_id": "abc-def-123",
    "prefect_deployment_id": "dep-aemo-nem-prod",
    "worker_id": "worker-01"
  },
  "lineage": {
    "input_datasets": [],
    "output_datasets": ["raw.aemo_nem_dispatch_30min"],
    "downstream_runs": ["run-1730000100-dbt01"]
  },
  "retry_chain": [],
  "logs_url": "/v1/ingestion/runs/run-1730000000-abc12/logs",
  "prefect_ui_url": "https://prefect.ecolens.app/runs/abc-def-123"
}
```

---

## 2.4 `GET /v1/ingestion/failed`

Failed jobs needing attention. Powers the **Ingestion → Failed Jobs** tab.

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | ❌ (always live) |
| Latency P95 | < 200 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "meta": {
    "total_failed_24h": 12,
    "total_failed_7d": 47,
    "as_of": "2024-06-01T10:00:00Z"
  },
  "data": [
    {
      "run_id": "run-1716888000-pqr12",
      "pipeline_id": "pipe-ice-fuel",
      "source_id": "ds-fuel-ice",
      "status": "failed",
      "started_at": "2024-05-28T08:00:00Z",
      "finished_at": "2024-05-28T08:00:01.234Z",
      "duration_ms": 1234,
      "error": {
        "code": "missing_credentials",
        "message": "ICE_API_KEY not set in environment",
        "http_status": 401,
        "retryable": false
      },
      "retry_count": 0,
      "next_retry_at": null,
      "in_dlq": true,
      "can_retry_now": false
    },
    {
      "run_id": "run-1729812000-timeout01",
      "pipeline_id": "pipe-open-meteo",
      "source_id": "ds-open-meteo",
      "status": "failed",
      "started_at": "2024-05-25T18:00:00Z",
      "finished_at": "2024-05-25T18:00:30.000Z",
      "duration_ms": 30000,
      "error": {
        "code": "timeout",
        "message": "Source did not respond within 30s",
        "http_status": null,
        "retryable": true
      },
      "retry_count": 2,
      "next_retry_at": "2024-06-01T10:15:00Z",
      "in_dlq": false,
      "can_retry_now": true
    }
  ]
}
```

### `can_retry_now` rule

`true` if `retryable=true` AND `next_retry_at <= now` AND `in_dlq=false`.

---

## 2.5 `GET /v1/ingestion/retry-queue`

Items in the retry queue (delayed retries). Powers the **Ingestion → Retry Queue** tab.

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | ❌ (always live) |
| Latency P95 | < 150 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "meta": {
    "queue_size": 7,
    "oldest_queued_at": "2024-05-28T08:00:00Z",
    "as_of": "2024-06-01T10:00:00Z"
  },
  "data": [
    {
      "queue_id": "rq-1729812000-open-meteo",
      "run_id": "run-1729812000-timeout01",
      "pipeline_id": "pipe-open-meteo",
      "source_id": "ds-open-meteo",
      "queued_at": "2024-05-25T18:00:30Z",
      "next_retry_at": "2024-06-01T10:15:00Z",
      "retry_count": 2,
      "max_retries": 4,
      "last_error": {
        "code": "timeout",
        "message": "Source did not respond within 30s"
      },
      "backoff_strategy": "exponential",
      "backoff_base_seconds": 60
    }
  ]
}
```

### Backoff strategy

Retries use **exponential backoff** with full jitter:

| Retry # | Wait |
|---|---|
| 1 | 1 min ± 30s |
| 2 | 5 min ± 1 min |
| 3 | 15 min ± 5 min |
| 4 | 1 h ± 15 min |
| 5 (DLQ) | manual only |

---

## 2.6 `GET /v1/ingestion/scheduler`

Scheduler status (Prefect's view of the world).

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 10s Redis |
| Latency P95 | < 150 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "scheduler": {
    "status": "healthy",
    "as_of": "2024-06-01T10:00:00Z",
    "active_workers": 1,
    "total_workers": 1,
    "queue_depth": 0,
    "prefect_version": "3.0.0",
    "prefect_api_url": "http://prefect:4200/api"
  },
  "upcoming_runs": [
    {
      "run_id": "sched-1730000100-aemo-nem",
      "pipeline_id": "pipe-aemo-nem",
      "source_id": "ds-aemo-nem",
      "scheduled_at": "2024-06-01T10:05:00Z",
      "trigger": "schedule"
    },
    {
      "run_id": "sched-1730001000-custom",
      "pipeline_id": "pipe-custom-meters",
      "source_id": "ds-custom-1",
      "scheduled_at": "2024-06-01T10:05:00Z",
      "trigger": "schedule"
    },
    {
      "run_id": "sched-1730000100-bom",
      "pipeline_id": "pipe-bom",
      "source_id": "ds-bom",
      "scheduled_at": "2024-06-01T10:30:00Z",
      "trigger": "schedule"
    }
  ],
  "recent_runs": [
    {
      "run_id": "run-1730000000-abc12",
      "pipeline_id": "pipe-aemo-nem",
      "status": "success",
      "finished_at": "2024-06-01T10:00:00.479Z",
      "duration_ms": 479
    }
  ]
}
```

---

## 2.7 `POST /v1/ingestion/{id}/pause`

Pause a pipeline (stops future scheduled runs; does not cancel in-flight).

| Aspect | Value |
|---|---|
| Auth | 🔒 admin only |
| Latency P95 | < 100 ms |
| Idempotent | ✅ (pausing an already-paused pipeline returns 200, no-op) |

### Path parameters

| Param | Type | Description |
|---|---|---|
| `id` | string | Pipeline ID (`pipe-aemo-nem`) |

### Request body

```json
{
  "reason": "Source returning 401s — investigating with vendor"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `reason` | string | ⚠️ | Free-text reason (logged, shown in audit) |

### Response 200

```json
{
  "id": "pipe-ice-fuel",
  "status": "paused",
  "paused_at": "2024-06-01T10:05:00Z",
  "paused_by": "diptu@ecolens.com",
  "reason": "Source returning 401s — investigating with vendor",
  "in_flight_runs": 0,
  "next_scheduled_run": null
}
```

### Errors

| Status | Code | When |
|---|---|---|
| 404 | `not_found` | No pipeline with this id |
| 409 | `cannot_pause_dbt` | Cannot pause `pipe-dbt-warehouse` (it's the only transform pipeline) |

---

## 2.8 `POST /v1/ingestion/{id}/resume`

Resume a paused pipeline.

| Aspect | Value |
|---|---|
| Auth | 🔒 admin only |
| Latency P95 | < 100 ms |
| Idempotent | ✅ (resuming an active pipeline returns 200, no-op) |

### Path parameters

| Param | Type | Description |
|---|---|---|
| `id` | string | Pipeline ID |

### Response 200

```json
{
  "id": "pipe-ice-fuel",
  "status": "active",
  "resumed_at": "2024-06-01T10:10:00Z",
  "resumed_by": "diptu@ecolens.com",
  "next_scheduled_run": "2024-06-01T12:00:00Z"
}
```

---

# Section 3: Data Quality

## 3.1 `GET /v1/data-quality/summary`

Overall DQ summary. Powers the **Data Quality** dashboard header.

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 60s Redis |
| Latency P95 | < 200 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "as_of": "2024-06-01T10:00:00Z",
  "overall": {
    "pass_rate_pct_24h": 99.4,
    "pass_rate_pct_7d":  99.1,
    "total_tests_24h": 1247,
    "tests_passed_24h": 1239,
    "tests_failed_24h": 8,
    "tests_warned_24h": 14
  },
  "by_severity_24h": {
    "critical": 1,
    "high": 2,
    "medium": 5,
    "low": 14
  },
  "by_source_24h": [
    { "source_id": "ds-aemo-nem",     "pass_rate_pct": 100.0, "issues": 0 },
    { "source_id": "ds-aemo-wem",     "pass_rate_pct": 100.0, "issues": 0 },
    { "source_id": "ds-open-meteo",   "pass_rate_pct": 99.7,  "issues": 2 },
    { "source_id": "ds-bom",          "pass_rate_pct": 100.0, "issues": 0 },
    { "source_id": "ds-carbon",       "pass_rate_pct": 100.0, "issues": 0 },
    { "source_id": "ds-fuel-ice",     "pass_rate_pct": 0.0,   "issues": 12 },
    { "source_id": "ds-eia",          "pass_rate_pct": 99.9,  "issues": 1 },
    { "source_id": "ds-custom-1",     "pass_rate_pct": 99.4,  "issues": 3 },
    { "source_id": "ds-entsoe",       "pass_rate_pct": null,  "issues": 0 }
  ],
  "by_category_24h": {
    "completeness": 4,
    "validity": 2,
    "uniqueness": 1,
    "consistency": 0,
    "timeliness": 1
  }
}
```

### `null` for paused sources

`pass_rate_pct` is `null` for `ds-entsoe` because it's paused — no tests ran in the last 24h.

---

## 3.2 `GET /v1/data-quality/issues`

List open DQ issues. Powers the **Data Quality → Issues** list.

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 30s Redis |
| Latency P95 | < 200 ms |
| Idempotent | ✅ |

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `source_id` | string | — | Filter to one source |
| `severity` | enum | — | `critical`, `high`, `medium`, `low` |
| `category` | enum | — | `completeness`, `validity`, `uniqueness`, `consistency`, `timeliness` |
| `status` | enum | `open` | `open`, `acknowledged`, `resolved`, `suppressed` |
| `limit` | int | 50 | 1–200 |
| `cursor` | string | — | Opaque cursor |

### Response 200

```json
{
  "meta": { "total": 22, "filtered": 8 },
  "data": [
    {
      "id": "dq-1730000000-ice-missing-creds",
      "source_id": "ds-fuel-ice",
      "pipeline_id": "pipe-ice-fuel",
      "severity": "high",
      "category": "completeness",
      "title": "ICE credentials missing",
      "description": "12 consecutive runs failed with code 'missing_credentials'. No records fetched.",
      "first_seen_at": "2024-05-28T08:00:00Z",
      "last_seen_at": "2024-06-01T10:00:00Z",
      "occurrences": 12,
      "status": "open",
      "suggested_action": "Set ICE_API_KEY environment variable on data-pipeline service, or disable the source.",
      "auto_resolvable": false
    },
    {
      "id": "dq-1729812000-temp-outlier",
      "source_id": "ds-open-meteo",
      "pipeline_id": "pipe-open-meteo",
      "severity": "medium",
      "category": "validity",
      "title": "Temperature reading 65°C (expected < 50°C for station s3)",
      "description": "Outlier detected: station s3 reported 65°C at 2024-05-25 18:00. Likely sensor fault.",
      "first_seen_at": "2024-05-25T18:00:00Z",
      "last_seen_at": "2024-05-25T18:00:00Z",
      "occurrences": 1,
      "status": "acknowledged",
      "acknowledged_by": "diptu@ecolens.com",
      "acknowledged_at": "2024-05-25T19:00:00Z",
      "suggested_action": "Flag in forecast model; exclude from training window.",
      "auto_resolvable": true
    }
  ],
  "next_cursor": "eyJpZCI6ImRxLTE3MjA4MDAwMDAifQ",
  "has_more": true
}
```

---

## 3.3 `GET /v1/data-quality/outliers`

Statistical outliers (z-score > 3). Powers the **Data Quality → Outliers** list.

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 5 min Redis (recomputed every 5 min) |
| Latency P95 | < 300 ms |
| Idempotent | ✅ |

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `source_id` | string | — | Filter to one source |
| `metric` | string | — | e.g. `temperature_c`, `demand_mw`, `wind_speed_ms` |
| `z_score_min` | float | `3.0` | Minimum z-score (1–10) |
| `from` | ISO 8601 | `now - 7d` | Start of window |
| `to` | ISO 8601 | `now` | End of window |
| `limit` | int | 100 | 1–500 |

### Response 200

```json
{
  "meta": { "total": 47, "as_of": "2024-06-01T10:00:00Z" },
  "data": [
    {
      "id": "out-1729855200-temp-s3",
      "source_id": "ds-open-meteo",
      "metric": "temperature_c",
      "value": 65.2,
      "expected_range": { "low": -10.0, "high": 45.0 },
      "z_score": 5.4,
      "observed_at": "2024-05-25T18:00:00Z",
      "region": "NSW1",
      "station_id": "s3",
      "context": {
        "rolling_median_24h": 18.2,
        "rolling_std_24h": 4.1,
        "neighbor_stations": [
          { "station_id": "s2", "value": 18.5, "distance_km": 12.3 },
          { "station_id": "s4", "value": 17.8, "distance_km": 8.7 }
        ]
      },
      "linked_issue_id": "dq-1729812000-temp-outlier"
    }
  ]
}
```

---

## 3.4 `GET /v1/data-quality/schema`

Schema drift report (column additions, removals, type changes).

| Aspect | Value |
|---|---|
| Auth | JWT — admin or analyst |
| Cache | 5 min Redis |
| Latency P95 | < 200 ms |
| Idempotent | ✅ |

### Response 200

```json
{
  "as_of": "2024-06-01T10:00:00Z",
  "drifts": [
    {
      "source_id": "ds-aemo-nem",
      "table": "raw.aemo_nem_dispatch_30min",
      "severity": "low",
      "kind": "column_added",
      "column": "renewable_pct",
      "old_type": null,
      "new_type": "float8",
      "first_seen_at": "2024-05-30T08:00:00Z",
      "auto_adapted": true,
      "action_required": false
    },
    {
      "source_id": "ds-bom",
      "table": "raw.bom_observations_30min",
      "severity": "medium",
      "kind": "type_changed",
      "column": "wind_gust_kmh",
      "old_type": "int4",
      "new_type": "float8",
      "first_seen_at": "2024-05-20T12:00:00Z",
      "auto_adapted": true,
      "action_required": false,
      "downstream_impact": "LSTM training re-scheduled for next cron window"
    }
  ],
  "summary": {
    "total_drifts_24h": 2,
    "auto_adapted": 2,
    "needs_action": 0
  }
}
```

### `kind` values

| Value | Meaning |
|---|---|
| `column_added` | New column appeared |
| `column_removed` | Column disappeared |
| `type_changed` | Column type changed (e.g. `int4` → `float8`) |
| `nullable_changed` | Nullability flipped |

---

## 3.5 `POST /v1/data-quality/recheck/{source}`

Re-run all DQ tests for one source (e.g. after manual fix).

| Aspect | Value |
|---|---|
| Auth | 🔒 admin only |
| Latency P95 | < 200 ms (returns 202, tests run in Prefect) |
| Idempotent | ✅ via `Idempotency-Key` (TTL: 1 hour) |

### Path parameters

| Param | Type | Description |
|---|---|---|
| `source` | string | Source ID |

### Request body

```json
{
  "tests": ["completeness", "validity", "uniqueness", "consistency", "timeliness"],
  "window": "P7D"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `tests` | string[] | all 5 | Which test categories to re-run |
| `window` | ISO 8601 duration | `P1D` | How far back to check (1d–30d) |

### Response 202

```json
{
  "recheck_id": "rc-1730000300-aemo-nem",
  "source_id": "ds-aemo-nem",
  "status": "queued",
  "tests": ["completeness", "validity", "uniqueness", "consistency", "timeliness"],
  "window": "P7D",
  "estimated_completion_at": "2024-06-01T10:01:00Z",
  "result_url": "/v1/data-quality/issues?source_id=ds-aemo-nem&status=open"
}
```

### Errors

| Status | Code | When |
|---|---|---|
| 404 | `not_found` | No source with this id |
| 409 | `recheck_in_progress` | Another recheck is already running for this source |

---

# Summary

| # | Endpoint | Method | Cache | P95 |
|---|---|---|---|---|
| 1.1 | `/v1/data-sources` | GET | 30s | < 80 ms |
| 1.2 | `/v1/data-sources/{id}` | GET | 30s | < 60 ms |
| 1.2 | `/v1/data-sources/{id}` | PATCH | — | < 120 ms |
| 1.3 | `/v1/data-sources/{id}/run` | POST | — | < 200 ms (202) |
| 1.4 | `/v1/data-sources/{id}/backfill` | POST | — | < 200 ms (202) |
| 1.5 | `/v1/data-sources/{id}/health` | GET | 10s | < 100 ms |
| 1.6 | `/v1/data-sources/{id}/history` | GET | 60s | < 200 ms |
| 2.1 | `/v1/ingestion/pipelines` | GET | 15s | < 100 ms |
| 2.2 | `/v1/ingestion/runs` | GET | 30s | < 200 ms |
| 2.3 | `/v1/ingestion/runs/{id}` | GET | — | < 200 ms |
| 2.4 | `/v1/ingestion/failed` | GET | — | < 200 ms |
| 2.5 | `/v1/ingestion/retry-queue` | GET | — | < 150 ms |
| 2.6 | `/v1/ingestion/scheduler` | GET | 10s | < 200 ms |
| 2.7 | `/v1/ingestion/{id}/pause` | POST | — | < 100 ms |
| 2.8 | `/v1/ingestion/{id}/resume` | POST | — | < 100 ms |
| 3.1 | `/v1/data-quality/summary` | GET | 60s | < 200 ms |
| 3.2 | `/v1/data-quality/issues` | GET | 30s | < 200 ms |
| 3.3 | `/v1/data-quality/outliers` | GET | 5 min | < 300 ms |
| 3.4 | `/v1/data-quality/schema` | GET | 5 min | < 200 ms |
| 3.5 | `/v1/data-quality/recheck/{source}` | POST | — | < 200 ms (202) |

**Total: 20 endpoint methods across 3 sections (Data Sources, Ingestion, Data Quality).**

The next parts (`/workspace/API_REFERENCE_DATA_PIPELINE_2.md`) will cover Sections 4–14: Emissions, Forecast, Analytics, ML Platform, Operational Tasks, System Health, Anomaly Detection, Warehouse.
