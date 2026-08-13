# infra/docker/forecast-api.Dockerfile
#
# Serves the trained demand-forecast model, plus derived emissions/
# footprint reads from the Postgres warehouse `services/waerehouse`'s dbt
# project builds. Also trains/tunes/evaluates/prunes models as of the
# data-pipeline training migration (this service's own README.md
# documents the cutover) -- the old "forecast-api never trains" service-
# boundary rule is retired. This one image serves two docker-compose
# roles, picked via `command:`: `api` (default `CMD`, the FastAPI app)
# and `train-worker` (`command: ["ecolens-forecast", "train-worker"]`,
# the RabbitMQ training-trigger consumer -- see that service's own
# comment in `docker-compose.yml`).
#
# Build context is the repo root (docker-compose.yml's `context: .`), but
# forecast-api is its own independent `uv` project now -- not a member of
# the root workspace (its restructured package is named `app`, same as
# data-pipeline's; sharing one workspace venv would collide the two) --
# so its lockfile lives in `services/forecast-api/` and is synced there.
#
# Multi-stage (mirrors `infra/docker/ingestion.Dockerfile`'s own pattern):
# `builder` has the full `uv` + apt build toolchain and produces the
# synced `.venv` + source tree; `runtime` copies only that finished result
# onto a fresh `python:3.12-slim` base, without `uv`/`uvx`/apt caches ever
# entering the shipped image. `torch` resolves from the CPU-only PyPI
# index (`services/forecast-api/pyproject.toml`'s `[tool.uv.sources]` --
# this service never runs on GPU infra) -- that alone drops ~2.7GB of
# unusable `nvidia-*`/`triton` CUDA packages that used to dominate this
# image's size; this multi-stage split is the remaining, smaller win on
# top of that (no `uv`/`uvx` binaries or dependency-resolution
# intermediates in the shipped image).

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /uvx /usr/local/bin/

WORKDIR /app/services/forecast-api

# Dependency layer first (cheap to cache -- only invalidated by lockfile/
# pyproject changes, not by every source edit).
COPY services/forecast-api/pyproject.toml services/forecast-api/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Now the actual source, and the real sync.
COPY services/forecast-api .
RUN uv sync --no-dev --frozen


FROM python:3.12-slim AS runtime

# `tini` as real PID 1 -- same reasoning `ingestion.Dockerfile`'s own
# comment gives for its `worker` role (reaps any reparented child,
# faithfully forwards a real deploy/restart's `SIGTERM`); harmless for
# the single-process `api` role too.
#
# `wget` -- docker-compose.yml's own healthcheck for the `api` role
# (`CMD wget -qO- http://localhost:8000/v1/healthz`) needs it on PATH;
# `python:3.12-slim` doesn't ship it. Same real, previously-disclosed gap
# `warehouse.Dockerfile`'s own comment named this file for ("ingestion/
# forecast-api install neither wget nor curl") -- fixed here now that
# this file's being touched anyway.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini wget \
    && rm -rf /var/lib/apt/lists/*

# Real, unprivileged runtime user -- the `builder` stage above still runs
# as root (needed for `uv sync`), but nothing in the runtime image needs
# root once the venv + source are just being executed. Fixed UID/GID
# (not left to `useradd`'s own default allocation) so file ownership is
# reproducible across rebuilds. Safe here: this service never writes to
# a local persistent path (only `tempfile.TemporaryDirectory()`'s
# `/tmp`, world-writable by default, for scratch model artifacts during
# training) -- no volume `chown` needed the way `ingestion`'s own
# `data/staging` mount required.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app/services/forecast-api

# Only the finished venv + source tree from `builder` -- no `uv`/`uvx`
# binaries, no apt/uv package cache layers, no dependency-resolution
# intermediates ship in the final image. Owned by the real runtime user,
# not root, from the moment it lands in this stage.
COPY --from=builder --chown=app:app /app/services/forecast-api /app/services/forecast-api

ENV PATH="/app/services/forecast-api/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 8000

# `tini` as the real entrypoint, the default `CMD` as its one managed
# child -- `--` marks the end of `tini`'s own args so everything after is
# exec'd as-is. `docker-compose.yml`'s `train-worker` service overrides
# `command:` wholesale (`["ecolens-forecast", "train-worker"]`), which
# lands as `tini`'s args the same way -- same entrypoint+subcommand-
# override shape `ingestion.Dockerfile` already uses, just with a plain
# `uvicorn` invocation as the default child instead of a CLI subcommand.
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
