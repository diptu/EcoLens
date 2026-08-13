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
#
# Multi-stage (mirrors `infra/docker/ingestion.Dockerfile`'s own
# pattern): `builder` has the full `uv` toolchain and produces the synced
# `.venv` + source tree; `runtime` copies only that finished result onto
# a fresh `python:3.12-slim` base, so `uv`/`uvx`/the dependency-resolution
# cache never enter the shipped image. `git`/`wget` move to the `runtime`
# stage below (not `builder`) -- both are real runtime needs, not build-
# time ones (see that stage's own comment).

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

WORKDIR /app/services/waerehouse

# Dependency layer first (cheap to cache -- only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY services/waerehouse/pyproject.toml services/waerehouse/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Now the actual source (including the ported dbt/ecolens project), and
# the real sync.
COPY services/waerehouse .
RUN uv sync --no-dev --frozen


FROM python:3.12-slim AS runtime

# `tini` as real PID 1 -- same reasoning `ingestion.Dockerfile`'s own
# comment gives (reaps any reparented child, faithfully forwards a real
# deploy/restart's `SIGTERM`); harmless for the single-process `warehouse`
# role too.
#
# `git` -- `app/dbt/runner.py` shells out to the real `dbt` CLI as a
# runtime subprocess (`POST /v1/dbt/build`, this service's whole reason
# to exist), and dbt-postgres needs a real `git` on PATH for package
# installs (`dbt deps`) even though this project doesn't currently
# declare any -- cheap to have, expensive to debug the absence of later.
# Belongs in *this* stage, not `builder`: it's a runtime dependency of
# the `dbt` subprocess this image actually runs, not a `uv sync`-time one.
#
# `wget` -- docker-compose.yml's own healthcheck (`CMD wget -qO-
# http://localhost:8004/v1/healthz`) needs it on PATH; `python:3.12-slim`
# doesn't ship it. Real bug found live (`TODO.md` Phase 4) while
# verifying `docker compose up warehouse` end-to-end: `/v1/healthz`/
# `/v1/readyz` both answered correctly over the published port the whole
# time, but the container's own Docker healthcheck never once succeeded
# (`FailingStreak` climbing forever, `exec: "wget": executable file not
# found in $PATH`) -- the app was healthy, Docker just couldn't tell.
RUN apt-get update && apt-get install -y --no-install-recommends tini git wget \
    && rm -rf /var/lib/apt/lists/*

# Real, unprivileged runtime user -- the `builder` stage above still runs
# as root (needed for `uv sync`), but nothing in the runtime image needs
# root once the venv + source are just being executed. Same fixed
# UID/GID `ingestion.Dockerfile` uses (10001:app) -- this service reads
# the same shared `duckdb_staging` volume ingestion's own container
# writes, so matching IDs keeps permissions predictable across both
# without relying on world-readable bits alone.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app/services/waerehouse

# Only the finished venv + source tree from `builder` -- no `uv`/`uvx`
# binaries, no apt/uv package cache layers, no dependency-resolution
# intermediates ship in the final image. Owned by the real runtime user,
# not root, from the moment it lands in this stage.
COPY --from=builder --chown=app:app /app/services/waerehouse /app/services/waerehouse

ENV PATH="/app/services/waerehouse/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# `Settings.duckdb_staging_dir` (default `./data/staging`) resolves here
# -- the same shared `duckdb_staging` volume `services/ingestion`'s own
# Dockerfile mounts, read-only from this side (`app.db.duckdb_client`'s
# own module docstring). Created and owned by `app`, not root, so the
# non-root runtime user below can actually traverse into the mount point
# (the volume itself is mounted `:ro` in docker-compose.yml, but the
# mount point directory itself still needs to exist and be enterable).
RUN mkdir -p data/staging && chown -R app:app data/staging

USER app

EXPOSE 8004

# `tini` as the real entrypoint, `ecolens-warehouse` as its one managed
# child -- `--` marks the end of `tini`'s own args. `CMD` stays a plain
# subcommand (not baked into `ENTRYPOINT`) so `docker-compose.yml`'s
# `warehouse-consumer` service can override just it (`command: consume`)
# without needing to repeat `tini --` itself -- same pattern
# `ingestion.Dockerfile` already uses for its own worker/beat roles.
ENTRYPOINT ["tini", "--", "ecolens-warehouse"]
CMD ["serve"]
