# infra/docker/data-pipeline.Dockerfile
#
# One image, three roles, picked via docker-compose's `command:` override
# (or a one-off `docker compose exec data-pipeline ecolens-pipeline ...`):
#   - `serve`  — the FastAPI app (`/v1/ingest`, `/v1/dbt`, `/v1/data-sources`,
#                 ECO-D49; TODO.md's Ingestion section)
#   - `worker` — the RabbitMQ warehouse-sync consumer (`overview.md` §2)
#   - anything else — `ingest {source}` / `dbt {subcommand}` / `health`
#
# Build context is the repo root (docker-compose.yml's `context: .`) — this
# is a `uv` workspace (root pyproject.toml + services/data-pipeline's own),
# so the lockfile lives at the root and has to be copied from there.

FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependency layer first (cheap to cache — only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY pyproject.toml uv.lock ./
COPY services/data-pipeline/pyproject.toml services/data-pipeline/pyproject.toml
RUN uv sync --package data-pipeline --no-dev --frozen --no-install-project

# Now the actual source, and the real sync (installs the data-pipeline
# package itself — the `ecolens-pipeline` console script this image runs).
COPY services/data-pipeline services/data-pipeline
RUN uv sync --package data-pipeline --no-dev --frozen

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/services/data-pipeline

# `Settings.duckdb_staging_dir` (default `./data/staging`) resolves here —
# `docker-compose.yml` mounts the shared `duckdb_staging` volume at this
# same path on both the `data-pipeline` and `warehouse-sync` services, so
# whichever container stages a run's DuckDB file, the other can see it.
RUN mkdir -p data/staging

EXPOSE 8001

ENTRYPOINT ["ecolens-pipeline"]
CMD ["serve"]
