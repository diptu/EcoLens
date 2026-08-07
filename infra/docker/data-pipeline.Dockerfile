# infra/docker/data-pipeline.Dockerfile
#
# One image, three roles, picked via docker-compose's `command:` override
# (or a one-off `docker compose exec data-pipeline ecolens-pipeline ...`):
#   - `serve`  — the FastAPI app (`/v1/ingest`, `/v1/dbt`, `/v1/data-sources`,
#                 ECO-D49; TODO.md's Ingestion section)
#   - `worker` — the RabbitMQ warehouse-sync consumer (`overview.md` §2) --
#                a no-op once `Settings.warehouse_sync_consumer_enabled` is
#                flipped off (services/waerehouse/TODO.md Phase 4's cutover
#                switch)
#   - anything else — `ingest {source}` / `dbt {subcommand}` / `train-worker`
#     / `health`
#
# Build context is the repo root (docker-compose.yml's `context: .`), but
# this is now its own independent `uv` project -- not a member of the root
# workspace (TODO.md's "microservice independence" pass: this was the last
# service still coupled to the root workspace's lockfile; forecast-api/
# ingestion/waerehouse already made this same move earlier for the same
# reason -- each restructured package is named `app`, which would collide
# if more than one shared a workspace venv). Its lockfile now lives in
# `services/data-pipeline/` and is synced from there, same shape every
# sibling service's Dockerfile already uses.

FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

WORKDIR /app/services/data-pipeline

# Dependency layer first (cheap to cache — only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY services/data-pipeline/pyproject.toml services/data-pipeline/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Now the actual source, and the real sync (installs the data-pipeline
# package itself — the `ecolens-pipeline` console script this image runs).
COPY services/data-pipeline .
RUN uv sync --no-dev --frozen

ENV PATH="/app/services/data-pipeline/.venv/bin:$PATH"

# `Settings.duckdb_staging_dir` (default `./data/staging`) resolves here —
# `docker-compose.yml` mounts the shared `duckdb_staging` volume at this
# same path on both the `data-pipeline` and `warehouse-sync` services, so
# whichever container stages a run's DuckDB file, the other can see it.
RUN mkdir -p data/staging

EXPOSE 8001

ENTRYPOINT ["ecolens-pipeline"]
CMD ["serve"]
