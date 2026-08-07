# infra/docker/warehouse.Dockerfile
#
# The standalone warehouse service (services/waerehouse/README.md) --
# consumes landed events off RabbitMQ, loads staged DuckDB data into
# Postgres raw.*, enforces the rolling-window retention policy, runs dbt
# transforms on top. Never fetches from external providers or stages raw
# data itself -- that's ingestion's job.
#
# Build context is the repo root (docker-compose.yml's `context: .`), but
# warehouse is its own independent `uv` project -- not a member of the
# root workspace (its package is named `app`, same as data-pipeline's/
# ingestion's; sharing one workspace venv would collide them, same
# reasoning as forecast-api/ingestion's identical Dockerfiles) -- so its
# lockfile lives in `services/waerehouse/` and is synced there.

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

# dbt-postgres needs a real `git` on PATH for package installs
# (`dbt deps`) even though this project doesn't currently declare any
# packages -- cheap to have, expensive to debug the absence of later.
#
# wget -- docker-compose.yml's own healthcheck for this service
# (`CMD wget -qO- http://localhost:8004/v1/healthz`) needs it on PATH
# inside the container; `python:3.12-slim` doesn't ship it. Real bug
# found live (`TODO.md` Phase 4) while verifying `docker compose up
# warehouse` end-to-end: `/v1/healthz`/`/v1/readyz` both answered
# correctly over the published port the whole time, but the container's
# own Docker healthcheck never once succeeded (`FailingStreak` climbing
# forever, `exec: "wget": executable file not found in $PATH`) --
# the app was healthy, Docker just couldn't tell. The same gap exists in
# every sibling service's Dockerfile (`ingestion`/`forecast-api` install
# neither wget nor curl; `data-pipeline` installs curl, not wget, so its
# identical wget-based healthcheck is equally broken) -- out of scope to
# fix here since only this service was asked for, noted in `TODO.md` so
# it isn't lost.
RUN apt-get update && apt-get install -y --no-install-recommends git wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/services/waerehouse

# Dependency layer first (cheap to cache -- only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY services/waerehouse/pyproject.toml services/waerehouse/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Now the actual source (including the ported dbt/ecolens project), and
# the real sync.
COPY services/waerehouse .
RUN uv sync --no-dev --frozen

ENV PATH="/app/services/waerehouse/.venv/bin:$PATH"

# `Settings.duckdb_staging_dir` (default `./data/staging`) resolves here
# -- the same shared `duckdb_staging` volume `services/ingestion`'s own
# Dockerfile mounts, read-only from this side (`app.db.duckdb_client`'s
# own module docstring).
RUN mkdir -p data/staging

EXPOSE 8004

# `ENTRYPOINT` + a plain `CMD` (not a full uvicorn invocation) so
# `docker-compose.yml`'s `warehouse-consumer` service can override just
# the subcommand (`command: consume`) -- same pattern ingestion/data-
# pipeline's own Dockerfiles already use for their worker services.
ENTRYPOINT ["ecolens-warehouse"]
CMD ["serve"]
