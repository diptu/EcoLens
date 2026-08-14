# infra/docker/mlflow.Dockerfile
#
# The MLflow tracking server itself -- `docker-compose.yml`'s `mlflow`
# service supplies the actual `mlflow server ...` command (backend-store-
# uri/artifact-root are environment-dependent, so they're compose config,
# not baked into the image). This image just needs `mlflow` plus the
# client libraries its `--backend-store-uri postgresql://...` (psycopg2)
# and `--default-artifact-root s3://...` (boto3, for the MinIO/S3
# artifact store) options need to actually connect.
#
# Not a `uv`-workspace build like `warehouse.Dockerfile`/`forecast-
# api.Dockerfile` -- the MLflow server itself isn't part of either
# service's own package, just a pinned pip install matching the `mlflow`
# version both services depend on (pyproject.toml's `mlflow>=2.17`).
#
# Multi-stage, mirroring the other 3 images in this directory -- smaller
# win here specifically (every package below is a prebuilt wheel, nothing
# compiles from source, so there's no real build-toolchain residue to
# strip the way `uv sync`-based builds have), but it keeps this file
# structurally consistent with the rest of the fleet and costs nothing:
# `builder` installs into an isolated venv, `runtime` copies just that
# venv onto a fresh base, so pip's own download/wheel cache (already
# `--no-cache-dir`'d, but belt-and-braces against a future dependency
# that isn't) never has a layer to live in either way.

FROM python:3.12-slim AS builder

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Pinned to match forecast-api's actual resolved client version (its
# own `pyproject.toml` constraint is an unbounded `mlflow>=2.17`, so
# `uv sync` drifted this server's pin out of sync over time -- confirmed
# live 2026-08-14: client resolved to 3.15.0, this server was still on
# 2.17.2, and MLflow 3.x's client calls a `/api/2.0/mlflow/logged-models`
# endpoint the 2.x server doesn't have, 404ing every real training run's
# final registration step. Re-check this pin against forecast-api's
# actual resolved `mlflow` version (not its `pyproject.toml` floor)
# whenever that dependency bumps.
RUN pip install --no-cache-dir \
        mlflow==3.15.0 \
        psycopg2-binary==2.9.10 \
        boto3==1.35.99


FROM python:3.12-slim AS runtime

# `tini` as real PID 1 -- `mlflow server` itself forks multiple uvicorn
# worker processes (its own `--workers` handling under the hood), so this
# isn't just cosmetic consistency with the other images here: without a
# real init process, a worker that dies gets silently reparented with no
# reaper, and a real deploy/restart's `SIGTERM` has no guaranteed correct
# forwarding to the whole process tree.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Real, unprivileged runtime user -- nothing here needs root once the
# venv is just being executed. `--backend-store-uri`/`--default-
# artifact-root` are always external (Postgres/S3-compatible, per this
# service's own `docker-compose.yml` config) -- no local persistent
# volume, so no `chown` needed beyond the venv copy below.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder --chown=app:app /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 5000

# No default `CMD` -- `docker-compose.yml`'s `mlflow` service always
# supplies the real `mlflow server ...` command explicitly (backend-
# store-uri/artifact-root are environment-dependent), same as before this
# multi-stage rewrite. `tini --` still wraps whatever command a caller
# supplies.
ENTRYPOINT ["tini", "--"]
