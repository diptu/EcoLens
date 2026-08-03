#!/usr/bin/env bash
# Backs up MLflow's two stores (README's "scripts/backup-mlflow.sh runs
# daily"): the Postgres backend store (experiments/runs/metrics/params/
# registered models -- MLflow's `--backend-store-uri`, docker-compose.yml's
# `mlflow` service) and the MinIO/S3 artifact store (model files, `mlflow`
# service's `--default-artifact-root s3://${S3_BUCKET_MODELS}/mlflow`).
#
# MLflow's backend store lives in the *same* Postgres database as
# ecoLens's own tables (one `DATABASE_URL`, no separate MLflow database) --
# so the Postgres half of this is a full `pg_dump` of that database, not
# a selective dump of just MLflow's own tables. That's deliberate: it's
# simpler and more robust than hand-maintaining a list of MLflow's
# internal table names (which varies by MLflow version), and a full dump
# is what `pipeline/tasks/task.md`'s own recovery playbook already
# expects (`psql < /var/backups/ecolens/postgres-<date>.sql`).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$SERVICE_DIR/../../.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${DATABASE_URL:?DATABASE_URL must be set (via env or $ENV_FILE)}"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/ecolens}"
DATE_STAMP="$(date +%Y-%m-%d)"
PG_DUMP_FILE="$BACKUP_DIR/postgres-$DATE_STAMP.sql"

S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-http://localhost:9000}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-minioadmin}"
S3_SECRET_KEY="${S3_SECRET_KEY:-minioadmin}"
S3_BUCKET_MODELS="${S3_BUCKET_MODELS:-ecolens}"
ARTIFACT_BACKUP_DIR="$BACKUP_DIR/mlflow-artifacts-$DATE_STAMP"

mkdir -p "$BACKUP_DIR"

# psql/pg_dump don't understand the +asyncpg driver suffix our app's DSN uses.
PSQL_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"

echo "Backing up Postgres (backend store + everything else) to $PG_DUMP_FILE..."
pg_dump "$PSQL_URL" -f "$PG_DUMP_FILE"
gzip -f "$PG_DUMP_FILE"
echo "  wrote ${PG_DUMP_FILE}.gz"

artifact_backup_written=""
if command -v mc >/dev/null 2>&1; then
  echo "Backing up MLflow artifact bucket (s3://${S3_BUCKET_MODELS}/mlflow) to $ARTIFACT_BACKUP_DIR..."
  mc alias set ecolens-backup-source "$S3_ENDPOINT_URL" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" >/dev/null
  mkdir -p "$ARTIFACT_BACKUP_DIR"
  mc mirror --overwrite "ecolens-backup-source/${S3_BUCKET_MODELS}/mlflow" "$ARTIFACT_BACKUP_DIR"
  echo "  wrote $ARTIFACT_BACKUP_DIR"
  artifact_backup_written="$ARTIFACT_BACKUP_DIR"
else
  echo "mc (MinIO client) not found on PATH -- skipping artifact bucket backup." >&2
  echo "Install it (https://min.io/docs/minio/linux/reference/minio-mc.html) to back up model artifacts too." >&2
fi

echo "Backup complete: ${PG_DUMP_FILE}.gz${artifact_backup_written:+, $artifact_backup_written}"
