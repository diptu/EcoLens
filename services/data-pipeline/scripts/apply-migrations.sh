#!/usr/bin/env bash
# Applies every services/data-pipeline/migrations/*.sql file, in order,
# against DATABASE_URL. Idempotent: each migration guards its own DDL
# (CREATE ... IF NOT EXISTS), so re-running this script is always safe --
# this script itself does no bookkeeping about what already ran.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$SERVICE_DIR/migrations"
ENV_FILE="${ENV_FILE:-$SERVICE_DIR/../../.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${DATABASE_URL:?DATABASE_URL must be set (via env or $ENV_FILE)}"

# psql doesn't understand the +asyncpg driver suffix our app's DSN uses.
PSQL_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"

if [ ! -d "$MIGRATIONS_DIR" ]; then
  echo "No migrations directory at $MIGRATIONS_DIR yet — nothing to apply."
  exit 0
fi

shopt -s nullglob
migrations=("$MIGRATIONS_DIR"/*.sql)
shopt -u nullglob

if [ ${#migrations[@]} -eq 0 ]; then
  echo "No .sql files in $MIGRATIONS_DIR yet — nothing to apply."
  exit 0
fi

for migration in "${migrations[@]}"; do
  echo "Applying $(basename "$migration")..."
  psql "$PSQL_URL" -v ON_ERROR_STOP=1 -f "$migration"
done

echo "All migrations applied."
