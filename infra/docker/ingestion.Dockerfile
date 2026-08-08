# infra/docker/ingestion.Dockerfile
#
# The standalone ingestion service (services/ingestion/TODO.md) --
# fetches from external providers, flags anomalies, stages in DuckDB,
# publishes a landed event. Never writes raw.*/runs dbt (that stays
# services/waerehouse's job).
#
# Build context is the repo root (docker-compose.yml's `context: .`), but
# ingestion is its own independent `uv` project -- not a member of the
# root workspace (its package is named `app`, same as forecast-api's;
# sharing one workspace venv would collide the two) -- so its lockfile
# lives in `services/ingestion/` and is synced there.
#
# Multi-stage (`services/ingestion/TODO.md` Phase 1's own "multi-stage
# Dockerfile" item, closed 2026-08-08): `builder` has the full `uv` +
# apt build toolchain and produces the synced `.venv` + source tree;
# `runtime` copies only that finished result onto a fresh `python:3.12-
# slim` base, without `uv`/`uvx`/apt caches/pip wheel caches ever
# entering the shipped image. `uv`'s own venvs are relocatable (pure
# Python + compiled wheels, no build-time absolute-path baking for a
# same-Python-version copy like this), so `COPY --from=builder` of the
# `.venv` directory works without a re-sync in the runtime stage.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

WORKDIR /app/services/ingestion

# Dependency layer first (cheap to cache -- only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY services/ingestion/pyproject.toml services/ingestion/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Now the actual source, and the real sync.
COPY services/ingestion .
RUN uv sync --no-dev --frozen


FROM python:3.12-slim AS runtime

WORKDIR /app/services/ingestion

# Only the finished venv + source tree from `builder` -- no `uv`/`uvx`
# binaries, no apt/uv package cache layers, no dependency-resolution
# intermediates ship in the final image.
COPY --from=builder /app/services/ingestion /app/services/ingestion

ENV PATH="/app/services/ingestion/.venv/bin:$PATH"

# `Settings.duckdb_staging_dir` (default `./data/staging`) resolves here
# -- a shared volume with `services/waerehouse`'s own read side.
RUN mkdir -p data/staging

EXPOSE 8003

# `ENTRYPOINT` + a plain `CMD` (not a full uvicorn invocation) so
# `docker-compose.yml`'s `ingestion-worker`/`ingestion-beat` services can
# override just the subcommand (`command: worker --loglevel=info`) --
# same pattern forecast-api's own Dockerfile uses for its `train-worker`
# service.
ENTRYPOINT ["ecolens-ingestion"]
CMD ["serve"]
