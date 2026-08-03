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
# Not a `uv`-workspace build like `data-pipeline.Dockerfile`/
# `forecast-api.Dockerfile` -- the MLflow server itself isn't part of
# either service's own package, just a pinned pip install matching the
# `mlflow` version both services depend on (pyproject.toml's `mlflow>=2.17`).

FROM python:3.12-slim

RUN pip install --no-cache-dir \
        mlflow==2.17.2 \
        psycopg2-binary==2.9.10 \
        boto3==1.35.99

EXPOSE 5000
