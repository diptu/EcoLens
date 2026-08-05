# infra/docker/ingestion.Dockerfile
#
# The standalone ingestion service (services/ingestion/TODO.md) --
# fetches from external providers, flags anomalies, stages in DuckDB,
# publishes a landed event. Never writes raw.*/runs dbt (that stays
# warehouse's job, still in data-pipeline until a future warehouse
# split -- see docs/data/ingestion.md's service-boundary note).
#
# Build context is the repo root (docker-compose.yml's `context: .`), but
# ingestion is its own independent `uv` project -- not a member of the
# root workspace (its package is named `app`, same as data-pipeline's;
# sharing one workspace venv would collide the two, same reasoning as
# forecast-api's identical Dockerfile) -- so its lockfile lives in
# `services/ingestion/` and is synced there.

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

WORKDIR /app/services/ingestion

# Dependency layer first (cheap to cache -- only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY services/ingestion/pyproject.toml services/ingestion/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Now the actual source, and the real sync.
COPY services/ingestion .
RUN uv sync --no-dev --frozen

ENV PATH="/app/services/ingestion/.venv/bin:$PATH"

# `Settings.duckdb_staging_dir` (default `./data/staging`) resolves here
# -- see `services/ingestion/TODO.md` Phase 2 for why this is a temporary
# bridge (a shared volume with whatever still runs `warehouse_sync`), not
# the end state.
RUN mkdir -p data/staging

EXPOSE 8003

# `ENTRYPOINT` + a plain `CMD` (not a full uvicorn invocation) so
# `docker-compose.yml`'s `ingestion-worker`/`ingestion-beat` services can
# override just the subcommand (`command: worker --loglevel=info`) --
# same pattern data-pipeline's own Dockerfile already uses for its
# `worker`/`train-worker` services.
ENTRYPOINT ["ecolens-ingestion"]
CMD ["serve"]
