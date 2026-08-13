# API Reference — Part 2 of 4

> `API_SPECEFICATIONS.md` ("Part 1 of 4") covers Data Sources, Ingestion
> Pipelines, and Data Quality — all `data-pipeline` endpoints. This
> document covers the remaining groups it names (Emissions, Forecast,
> Analytics, ML, Operational, System Health, Anomaly, Warehouse), scoped
> to what's actually built rather than speccing all eight groups from
> scratch. See "Scope of this document" below before reading further.

## Scope of this document

Three of the eight groups this doc was supposed to cover already have a
real spec elsewhere and aren't repeated here:

| Group | Where it's actually specified |
|---|---|
| Operational | `API_SPECEFICATIONS.md` §2, Ingestion Pipelines (`GET /v1/ingestion/*`, `POST /v1/ingestion/{id}/{pause,resume}`) |
| Anomaly | `API_SPECEFICATIONS.md` §3, Data Quality (`GET /v1/data-quality/*`) |
| Analytics | **Not built.** No analytics query API exists anywhere in this codebase (no endpoint lets a caller run an ad-hoc aggregation over the warehouse) — nothing to document yet. Tracked in `TODO.md`'s Forecasting section as a real gap, not silently assumed covered by Emissions/Forecast. |

The remaining five (Emissions, Forecast, ML, System Health, Warehouse)
are covered below, against what's actually running.

**Two services, not one.** Unlike Part 1 (all `data-pipeline`), the
endpoints below split across two independent services:

| Service | Endpoints here | Auth | Base URL |
|---|---|---|---|
| `forecast-api` | System Health, Forecast, Emissions, ML (`/v1/model`) | **None yet** — see the callout below | `http://localhost:8000` (dev) |
| `data-pipeline` | Warehouse (`/v1/dbt/*`) | **None yet** — pre-dates `API_SPECEFICATIONS.md`'s JWT convention | `http://localhost:8001` (dev) |

> ⚠️ **`forecast-api`'s endpoints are unauthenticated in this pass.**
> `README.md` frames `/v1/forecast`/`/v1/emissions`/`/v1/footprint` as
> public-ish, rate-limited endpoints (not admin-gated like `data-
> pipeline`'s `/v1/data-sources*`), but the Redis-token-bucket rate
> limiting it promises isn't implemented either — this is the same gap
> `TODO.md`'s IAM section already tracks ("Add the Redis-token-bucket
> rate limiting... not implemented on any endpoint yet"), not a new one.
> `/v1/dbt/*` predates `API_SPECEFICATIONS.md`'s JWT/error-envelope
> convention entirely (`api/errors.py`'s own docstring already flags
> this) and still returns FastAPI's default `{"detail": ...}` error
> shape, not the `{"error": {...}}` envelope Part 1 defines — noted here
> rather than glossed over.

---

## Conventions

Same as Part 1's, reproduced here for a reader who only has this file
open:

| Symbol | Meaning |
|---|---|
| ✅ required | Field must be present |
| ⚠️ optional | Field can be omitted |
| ISO 8601 | UTC timestamps with `Z` suffix (`2024-06-01T10:00:00Z`) |

### Standard error envelope (`forecast-api` endpoints only — `/v1/dbt/*` is the exception noted above)

```json
{
  "error": {
    "code": "not_found",
    "message": "No carbon-intensity data available for region 'NSW1'",
    "field": null,
    "request_id": null
  }
}
```

`request_id` is always `null` — `forecast-api` has no request-ID
middleware yet (`data-pipeline`'s exists, `api/middleware.py`); a real
gap, not a placeholder left in on purpose.

---

# Section 4: System Health (`forecast-api`)

## 4.1 `GET /v1/healthz`

| Aspect | Value |
|---|---|
| Auth | None |
| Latency P95 | < 20 ms |

Liveness only — 200 if the process is up, no dependency checks.

```json
{ "status": "ok" }
```

## 4.2 `GET /v1/readyz`

| Aspect | Value |
|---|---|
| Auth | None |
| Latency P95 | < 200 ms |

Readiness — checks Postgres (`SELECT 1`), Redis (`PING`), and whether a
model is currently loaded. Returns **503** (not 200) when any component
is down, so a load balancer/orchestrator's readiness probe actually
reacts to it — the body reports the same information either way.

```json
{
  "ready": false,
  "database": { "ok": true, "detail": null },
  "redis": { "ok": true, "detail": null },
  "model": { "ok": false, "detail": "no Production model version loaded yet" }
}
```

---

# Section 5: Forecast (`forecast-api`)

## 5.1 `GET /v1/regions`

| Aspect | Value |
|---|---|
| Auth | None |
| Cache | None (static) |

Static list of the 6 regions this platform ingests for — not a DB query
(`api/routers/regions.py`'s own docstring explains why a static list is
fine here).

```json
{
  "data": [
    { "id": "NSW1", "name": "New South Wales", "network": "NEM" },
    { "id": "QLD1", "name": "Queensland", "network": "NEM" },
    { "id": "VIC1", "name": "Victoria", "network": "NEM" },
    { "id": "SA1", "name": "South Australia", "network": "NEM" },
    { "id": "TAS1", "name": "Tasmania", "network": "NEM" },
    { "id": "WEM", "name": "Western Australia (SWIS)", "network": "WEM" }
  ]
}
```

## 5.2 `GET /v1/forecast`

| Aspect | Value |
|---|---|
| Auth | None |
| Cache | 60s Redis, keyed by `(region, model_version)` |
| Errors | 503 `model_not_loaded`, 503 `insufficient_data`, 503 `model_not_trained_for_region` |

Runs live inference against the currently-loaded `Production` `DemandLSTM`
(`ml/registry.py`'s hot-reloaded bundle) over the most recent warehouse
window for `region`.

### Query parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `region` | string | ✅ | e.g. `NSW1` |
| `horizon` | string | ⚠️ | **Accepted but ignored in v0** — see caveat below |
| `interval` | string | ⚠️ | **Accepted but ignored in v0** — see caveat below |

> ⚠️ **v0 does not resample to an arbitrary requested `horizon`/
> `interval`.** The model predicts a fixed 48-step output at its
> training source's native cadence (4h at 5-min steps for a NEM region
> like NSW1 trained today; 24h at 30-min steps for a WEM region, if/when
> one is trained). The response's own `horizon`/`interval` fields always
> report what was *actually* computed, not an echo of the request —
> `api/routers/forecast.py`'s docstring has the full reasoning. Building
> real resampling to an arbitrary requested cadence is future work.

### Response 200

```json
{
  "region": "NSW1",
  "model": "lstm_demand@production",
  "generated_at": "2026-01-01T00:00:00Z",
  "horizon": "4h",
  "interval": "5m",
  "points": [
    { "ts": "2026-01-01T00:05:00Z", "p10": 5839.5, "p50": 5913.6, "p90": 5995.3, "unit": "MW" }
  ]
}
```

`p10`/`p90` are conformal-calibrated (`ml/conformal.py`) — a real,
finite-sample marginal coverage guarantee over `DemandLSTM`'s raw
quantile-head output, not the raw heads themselves. Verified end-to-end
against a real trained model: `test_coverage_calibrated` landed at 0.78
against a 0.8 (1-alpha) target on held-out data from an actual training
run, not just the synthetic-data unit test that also passes.

---

# Section 6: Emissions (`forecast-api`)

## 6.1 `GET /v1/emissions`

| Aspect | Value |
|---|---|
| Auth | None |
| Cache | 60s Redis |
| Errors | 404 `not_found` (no data for that region) |

Live carbon intensity for a region — most recent hour of
`raw_marts.fct_carbon_intensity` (`data-pipeline`'s dbt project,
`live_mix_weighted` method: generation-weighted average across that
hour's fuel mix, using `seeds/emissions_factors.csv`).

### Query parameters

| Param | Type | Required |
|---|---|---|
| `region` | string | ✅ |

### Response 200

```json
{
  "region": "NSW1",
  "as_of": "2025-12-31T23:00:00Z",
  "intensity_kgco2e_per_mwh": 489.47,
  "total_generation_mwh": 5996.88,
  "total_emissions_kgco2e": 2935293.55,
  "factors_version": "nger-2025-q4",
  "method": "live_mix_weighted"
}
```

## 6.2 `POST /v1/footprint`

| Aspect | Value |
|---|---|
| Auth | None |
| Cache | 300s Redis, keyed by `(region, start, end, kwh)` |
| Errors | 400 `invalid_period`, 404 `not_found` |

kgCO₂e for `kwh` consumed over `period`, using the generation-weighted
average intensity across that whole period (`sum(emissions) /
sum(generation)`, not an average of each hour's already-weighted
intensity — the latter would over-weight low-generation hours).

### Request body

```json
{ "region": "NSW1", "kwh": 420, "period": "2025-12-01T00:00Z/2025-12-31T23:59Z" }
```

`period` is `"start/end"` ISO 8601 interval notation — not a general
interval/duration parser, just the two-timestamps case
(`api/routers/footprint.py`'s `_parse_period`).

### Response 200

```json
{
  "region": "NSW1",
  "kwh": 420.0,
  "kg_co2e": 190.72,
  "intensity_kg_co2e_per_kwh": 0.4541,
  "method": "live_mix_weighted",
  "factors_version": "nger-2025-q4"
}
```

Verified against `README.md`'s own worked example (420 kWh @ 0.446
kgCO₂e/kWh → 187.32 kgCO₂e) via a unit test asserting that exact
arithmetic, and separately against real warehouse data end-to-end.

## 6.3 `WS /v1/stream/emissions`

| Aspect | Value |
|---|---|
| Auth | None |
| Update cadence | `Settings.stream_interval_seconds` (default 300s / 5 min) |

Connect with `?region=NSW1`; missing `region` closes the connection with
code `4400`. Pushes the same shape `GET /v1/emissions` returns (minus
`total_generation_mwh`/`total_emissions_kgco2e`) as a JSON text frame on
every interval tick, re-reading the warehouse each time (no
`LISTEN`/`NOTIFY`, no change-feed — a fresh read is simple and correct
at a 5-minute cadence, not built to scale past that).

```json
{
  "region": "NSW1",
  "as_of": "2025-12-31T23:00:00+00:00",
  "intensity_kgco2e_per_mwh": 489.47,
  "factors_version": "nger-2025-q4"
}
```

---

# Section 7: ML (`forecast-api`)

## 7.1 `GET /v1/model`

| Aspect | Value |
|---|---|
| Auth | None |

Metadata for whatever model version `forecast-api` currently has loaded
(`ml/registry.py`'s `ModelRegistry.bundle`, hot-reloaded on a background
poll — see `TODO.md`'s "Non-Blocking Training Architecture" checklist
for the atomic-swap mechanism this relies on).

### Response 200

```json
{
  "status": "loaded",
  "name": "lstm_demand",
  "version": "1",
  "stage": "Production",
  "run_id": "5e7c0e57f15941c08cc895b8042e9ed9",
  "loaded_at": "2026-01-01T00:00:00Z",
  "git_sha": "170059fcb32f36e63953ca1d16196d47c179875f",
  "horizon": 48,
  "lookback": 48,
  "metrics": { "test_mape": 0.79, "test_coverage_calibrated": 0.78 }
}
```

`status: "not_loaded"` (all other fields `null`/`{}`) before the first
model is ever trained+promoted — a real, expected state, not an error.

There is no endpoint here to *trigger* training or promotion over HTTP,
by design (`README.md`'s service-boundary rule: `forecast-api` never
trains) — that's `ecolens-pipeline train`/`make train` and
`scripts/promote_model.sh`, both CLI-only, both in `data-pipeline`.

---

# Section 8: Warehouse (`data-pipeline`)

## 8.1 `POST /v1/dbt/{subcommand}`

| Aspect | Value |
|---|---|
| Auth | None (pre-dates the JWT convention — see the callout above) |
| `subcommand` | `build`, `run`, or `test` |

Runs the matching dbt subcommand against `data-pipeline`'s dbt project
(`dbt_runner.run_dbt`, offloaded via `asyncio.to_thread` since it's a
blocking subprocess call). Same path `ecolens-pipeline dbt
{build,run,test}` uses.

### Request body

```json
{ "target": "prod", "extra_args": ["--select", "stg_aemo_nem_dispatch"] }
```

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | ⚠️ | Defaults to `Settings.dbt_target` (`"prod"`) |
| `extra_args` | string[] | ⚠️ | Passed straight through to the `dbt` CLI |

### Response 200

```json
{ "subcommand": "build", "target": "prod", "exit_code": 0 }
```

### Errors

| Status | When |
|---|---|
| 500 | dbt exited non-zero — `{"detail": "dbt build failed with exit code 1"}` (FastAPI's default shape, not the `{"error": {...}}` envelope — see the callout above) |

There is no `GET` endpoint to list past dbt run history (unlike
`meta._ingest_log`'s ingestion-run history, dbt runs aren't logged to
any table — the same gap `API_SPECEFICATIONS.md` §2's implementation
note in Part 1 already flags for `pipe-dbt-warehouse`'s always-empty
stats).
