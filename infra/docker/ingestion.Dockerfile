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
#
# Prod-grade hardening pass (2026-08-12, `TODO.md`'s Railway deployment
# plan): non-root runtime user + `tini` as PID 1, see the `runtime`
# stage below for the real reasoning on each.

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

# Real, hard blocker hit deploying to a Namecheap Quasar VPS
# (2026-09-21): its hypervisor exposes only a generic `QEMU Virtual CPU
# version 2.5+` to the guest -- missing sse4_2/popcnt/etc, below the
# "x86-64-v2" baseline every PyPI numpy/scipy wheel has required since
# numpy's meson-based build (~2.x). Importing numpy on that box aborted
# immediately with `RuntimeError: NumPy was built with baseline
# optimizations: (X86_V2) but your machine doesn't support: (X86_V2)` --
# not a runtime-togglable dispatch feature, the *compiled minimum* the
# prebuilt wheel targets, confirmed by reading numpy's own CPU dispatch
# init code, not guessed. Rebuilding from source with
# `-Dcpu-baseline=none -Dcpu-dispatch=none` (pure portable x86-64, no
# SIMD requirement) fixes it -- verified directly on that VPS (~3 min
# extra build time). scipy's own *prebuilt* wheel was separately
# verified fine once numpy alone was fixed (scipy has no equivalent
# `cpu-baseline`/`cpu-dispatch` meson option of its own -- tried it,
# `ERROR: Unknown option: "cpu-baseline"` -- and doesn't need one; its
# compiled extensions don't hard-abort on this CPU the way numpy's do).
# So numpy is the only package that actually needs this. No effect on
# modern CPUs (this rebuild is functionally a no-op there beyond build
# time), so unconditional here rather than gated behind a build arg.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gfortran pkg-config libopenblas-dev \
    && rm -rf /var/lib/apt/lists/* \
    && uv pip install pip \
    && .venv/bin/pip install --force-reinstall --no-deps --no-binary numpy \
         --config-settings=setup-args=-Dcpu-baseline=none \
         --config-settings=setup-args=-Dcpu-dispatch=none \
         numpy==2.5.1


FROM python:3.12-slim AS runtime

# `tini` as real PID 1, not `ecolens-ingestion` directly -- matters most
# for the `worker` role: Celery's prefork pool forks real OS child
# processes per task, and a process running as PID 1 without an init
# gets Linux's PID-1-specific responsibilities (reaping any child that
# ends up reparented to it, faithfully forwarding signals) with no
# default handling for either. `tini` is the standard, minimal fix --
# transparent otherwise, doesn't change how `serve`/`beat`'s own signal
# handling behaves (both are already single-process, no forking), just
# makes `worker` correctly reap zombies and propagate a real Railway
# restart/redeploy's `SIGTERM` instead of relying on the app process
# happening to behave correctly as PID 1 by accident.
#
# `wget` -- docker-compose.yml's own healthcheck for this role (`CMD
# wget -qO- http://localhost:8003/v1/healthz`) needs it on PATH;
# `python:3.12-slim` doesn't ship it. Real bug, confirmed live
# 2026-08-19: `/v1/healthz` answered fine over the published port the
# whole time, but Docker's own healthcheck never once succeeded (`exec:
# "wget": executable file not found in $PATH`, `FailingStreak` climbing
# forever) -- same fix `forecast-api.Dockerfile`/`warehouse.Dockerfile`
# already carry for the identical gap.
#
# `libopenblas0` -- the source-rebuilt numpy above (builder stage)
# links against OpenBLAS at import time; only `libopenblas-dev` was
# installed there, and multi-stage `COPY --from=builder` never carries
# apt packages across, just the venv itself. Without the runtime shared
# lib in *this* stage too, numpy import fails with `libopenblas.so.0:
# cannot open shared object file` -- real bug, hit immediately after
# the CPU-baseline fix above on the same VPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini wget libopenblas0 \
    && rm -rf /var/lib/apt/lists/*

# Real, unprivileged runtime user -- the `builder` stage above still
# runs as root (needed for `apt-get`/`uv sync`), but nothing in the
# runtime image needs root once the venv + source are just being
# executed. Fixed UID/GID (not left to `useradd`'s own default
# allocation) so file ownership is reproducible across rebuilds.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app/services/ingestion

# `WORKDIR` creates this directory as root *before* anything below runs
# -- the `COPY --chown=app:app` two lines down only stamps ownership on
# what it copies IN, never on the parent directory it lands inside, so
# without this the directory itself stays `root:root` (mode 755: not
# writable by `app`). Real bug, confirmed live 2026-08-19: Celery Beat
# (`ingestion-beat`, which writes its `celerybeat-schedule` file
# straight into this WORKDIR, the CWD it runs from) crash-looped on
# every single start with `PermissionError: [Errno 13] Permission
# denied: 'celerybeat-schedule'` -- reproduced directly with `touch
# celerybeat-schedule` as the `app` user before this fix, confirmed
# fixed after it.
RUN chown app:app /app/services/ingestion

# Only the finished venv + source tree from `builder` -- no `uv`/`uvx`
# binaries, no apt/uv package cache layers, no dependency-resolution
# intermediates ship in the final image. Owned by the real runtime user,
# not root, from the moment it lands in this stage.
COPY --from=builder --chown=app:app /app/services/ingestion /app/services/ingestion

ENV PATH="/app/services/ingestion/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# `Settings.duckdb_staging_dir` (default `./data/staging`) resolves here
# -- a shared volume with `services/waerehouse`'s own read side on a
# single-host deployment; pure local scratch space (never relied on for
# durability -- real data also always goes to R2, see `services/
# ingestion/TODO.md`'s Railway deployment plan) everywhere else. Created
# and owned by `app`, not root, so the non-root runtime user below can
# actually write to it.
RUN mkdir -p data/staging && chown -R app:app data/staging

USER app

EXPOSE 8003

# `tini` as the real entrypoint, `ecolens-ingestion` as its one managed
# child -- `--` marks the end of `tini`'s own args so everything after
# is exec'd as-is, not parsed as a `tini` flag. `CMD` stays a plain
# subcommand (not a full uvicorn invocation) so `docker-compose.yml`'s
# `ingestion-worker`/`ingestion-beat` services (and this same image's
# equivalent Railway services) can override just it (`command: worker
# --loglevel=info`) without needing to repeat `tini --` themselves --
# same pattern forecast-api's own Dockerfile uses for its `train-worker`
# service, now with the added `tini` wrapper underneath both.
ENTRYPOINT ["tini", "--", "ecolens-ingestion"]
CMD ["serve"]
