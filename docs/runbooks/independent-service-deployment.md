# Deploying each service on a separate machine

Every service in this repo (`services/data-pipeline`, `services/ingestion`,
`services/waerehouse`, `services/forecast-api`, `services/dashboard`,
`services/observility`) builds and runs standalone — none of their Docker
images require sibling services' source to exist (`infra/docker/*.Dockerfile`
each `COPY` only their own `services/<name>` directory, confirmed by
inspection). What follows is what actually changes once "on separate
machines" stops being a hypothetical and a given service really is on a
different host/network than the others.

## The short version

For most services, "independently deployable" was already true: every
connection (Postgres, Redis, RabbitMQ, MLflow, object storage) is
env-var-driven, not hardcoded to a Docker Compose service name — point
`DATABASE_URL`/`REDIS_URL`/`RABBITMQ_URL`/`MLFLOW_TRACKING_URI` at wherever
those real things are running and the service works. See each service's own
`.env.example` for the exact variables it reads.

**One real exception existed and has been fixed**: `services/ingestion`
handing staged data off to `services/data-pipeline`/`services/waerehouse`
relied on a *Docker named volume* (`duckdb_staging`) shared by all three
containers on one host — this only worked because they happened to share a
Docker network, not because of anything in the actual `publish_landed_event`
contract. Both consumers now fall back to downloading the run's snapshot from
object storage when the shared local file isn't there (see "Ingestion →
warehouse handoff" below) — this is what actually makes running
`services/ingestion` on its own machine work, not just build.

## Ingestion → warehouse handoff (the one real cross-machine requirement)

`services/ingestion`'s producer (`app/service/pipeline/tasks/_common.py`)
always does two things after a successful fetch: writes the staged rows to
its own local `DUCKDB_STAGING_DIR`, **and** uploads the same rows to object
storage (R2/MinIO), publishing both the local path and the object-storage
key/bucket in the same RabbitMQ event.

- **Same machine** (today's `docker compose up` default): both consumers
  (`services/data-pipeline`'s `warehouse_sync`, `services/waerehouse`'s
  `landed_events`) read the shared local file first — fast, no network
  round trip.
- **Different machines**: the shared volume isn't shared anymore. Both
  consumers now detect that (the local path just doesn't exist) and download
  the run's snapshot from object storage instead
  (`read_staged_with_fallback` / `read_run_with_fallback`).

**This means real, shared object storage credentials are required, not
optional, once ingestion moves to its own machine.** If either side falls
back to local MinIO instead of real R2 (`CLOUDFLARESTORAGE_*` unset), the two
machines are talking to two different, unrelated MinIO instances — the
consumer's download will 404, and the run will be marked `sync_failed` (loud,
not silent — but avoidable by just configuring R2 on both sides in the first
place). Set the identical `CLOUDFLARESTORAGE_ACCOUNT_ID` /
`CLOUDFLARESTORAGE_S3_API` / `CLOUDFLARESTORAGE_ACCESS_KEY_ID` /
`CLOUDFLARESTORAGE_SECRET_ACCESS_KEY` on `services/ingestion` **and**
whichever of `services/data-pipeline` / `services/waerehouse` is consuming
its events.

## The competing-consumer trap

`services/data-pipeline`'s `warehouse-sync` and `services/waerehouse`'s
`warehouse-consumer` both consume the **same** RabbitMQ queue
(`ecolens.landing`) today — root `docker-compose.yml` runs both
simultaneously, and they race for whichever message either one picks up
first. This is true regardless of machine placement, but it matters *more*
once you're deliberately choosing one service as the "real" warehouse
consumer for an independent deployment: if you deploy `services/waerehouse`
standalone and leave `services/data-pipeline`'s own `warehouse-sync` running
too (e.g. because `data-pipeline` is still deployed for its other routes),
set `WAREHOUSE_SYNC_CONSUMER_ENABLED=false` on the `data-pipeline` deployment
(`app/core/config.py`) so only one consumer is actually running. The flag
exists specifically for this — flipping it doesn't require removing
`data-pipeline`'s own consumer code, just disabling that one process.

## Observability across machines

`services/observility`'s Prometheus scrape targets are env-driven
(`DATA_PIPELINE_TARGET` / `INGESTION_TARGET` / `WAREHOUSE_TARGET` /
`FORECAST_API_TARGET`, see its own `.env.example`) — defaults match the
current Docker Compose service names for the common same-host case; point
any of them at a real `host:port` (or a Tailscale/VPN/internal-DNS name
reachable from wherever this Prometheus container runs) once that service
moves off this host.

**Metrics scraping crosses machines this way; log collection does not.**
Promtail (`services/observility/promtail/promtail-config.yml`) discovers
containers via `docker_sd_configs` against the local Docker socket — it
can only ever see containers running on the same host as the
observability stack itself. A service on a different machine won't have
its logs collected by this stack no matter how its Prometheus target is
configured; that would need its own Promtail (or equivalent) shipping to
the same Loki instance, which isn't set up here.

The older, simpler `infra/prometheus/prometheus.yml` (what the root
`docker-compose.yml`'s own `prometheus` service still runs by default) is
**not** templated this way — it's scoped to "everything on one host" by
design, with `services/observility` as its intended eventual replacement.
Use `services/observility` if any service needs to be monitored across
machines.

## Per-service required configuration

Each service's own `.env.example` is the source of truth — this table is
just a map of what actually differs when a dependency isn't on the same
host anymore.

| Service | Must be set for cross-machine deployment | Notes |
| --- | --- | --- |
| `services/data-pipeline` | `DATABASE_URL`, `MLFLOW_TRACKING_URI`, and (if consuming ingestion's events) the R2 block | `IAM_JWT_SECRET` must be changed from the placeholder default in any real deployment |
| `services/ingestion` | `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL`, and the R2 block (**required**, not optional, if any consumer is on a different machine — see above) | |
| `services/waerehouse` | `DATABASE_URL`, `RABBITMQ_URL`, and the R2 block (same requirement as above) | Had no `.env.example` until this pass — created one |
| `services/forecast-api` | `DATABASE_URL`, `MLFLOW_TRACKING_URI` (must point at the **same** MLflow server `data-pipeline` registers/promotes to) | |
| `services/dashboard` | `NEXT_PUBLIC_FORECAST_API_URL`, `NEXT_PUBLIC_DATA_PIPELINE_API_URL` | `.env.local`, not `.env` (Next.js convention); its own `.env.example` had stale variable names/ports from a previous API-client design — fixed this pass |
| `services/observility` | `DATA_PIPELINE_TARGET`/`INGESTION_TARGET`/`WAREHOUSE_TARGET`/`FORECAST_API_TARGET` | Only needed once a scraped service actually moves off this host — same-host defaults work unchanged otherwise |

## dbt's `prod` target

`services/data-pipeline/dbt/ecolens/profiles.yml` and
`services/waerehouse/dbt/ecolens/profiles.yml`'s `prod` target previously
defaulted `host` to the literal string `postgres` (the Docker Compose service
name) if `POSTGRES_HOST` wasn't set — silently wrong outside that one Docker
network. Fixed to have no default at all: `POSTGRES_HOST` is now required for
the `prod` target, and dbt fails immediately with a clear error if it's
missing, instead of quietly trying to resolve a hostname that only exists on
one specific Docker network.
