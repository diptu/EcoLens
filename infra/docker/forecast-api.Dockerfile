# infra/docker/forecast-api.Dockerfile
#
# Serves the trained demand-forecast model `data-pipeline` registers in
# MLflow, plus derived emissions/footprint reads from the Postgres
# warehouse `data-pipeline`'s dbt project builds. Never trains (README.md
# § Microservices service-boundary rule).
#
# Build context is the repo root (docker-compose.yml's `context: .`), but
# forecast-api is its own independent `uv` project now -- not a member of
# the root workspace (its restructured package is named `app`, same as
# data-pipeline's; sharing one workspace venv would collide the two) --
# so its lockfile lives in `services/forecast-api/` and is synced there.

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

WORKDIR /app/services/forecast-api

# Dependency layer first (cheap to cache -- only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY services/forecast-api/pyproject.toml services/forecast-api/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Now the actual source, and the real sync.
COPY services/forecast-api .
RUN uv sync --no-dev --frozen

ENV PATH="/app/services/forecast-api/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
