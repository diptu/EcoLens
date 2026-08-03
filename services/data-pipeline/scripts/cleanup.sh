#!/usr/bin/env bash
# Prunes TimescaleDB chunks older than RETENTION_MONTHS (default 18, per
# README's "scripts/cleanup.sh prunes TimescaleDB chunks older than 18
# months to keep disk usage bounded") from the 4 time-series raw.*
# hypertables. `raw.aemo_holidays` is deliberately excluded -- it's an
# annual calendar snapshot (task.md), not a time series you'd want a
# rolling retention window against; its total volume is trivial anyway
# (a few hundred rows/region/year).
#
# Safe to run against a non-Timescale Postgres (e.g. a plain local dev
# database): `drop_chunks` on a table that was never converted to a
# hypertable (migrations 0009/0012 no-op without the extension) just
# errors per-table, which this script reports and skips rather than
# aborting the whole run.
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
RETENTION_MONTHS="${RETENTION_MONTHS:-18}"

# psql doesn't understand the +asyncpg driver suffix our app's DSN uses.
PSQL_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"

HYPERTABLES=(
  "raw.openelectricity_mix"
  "raw.aemo_nem_dispatch"
  "raw.aemo_wem_dispatch"
  "raw.bom_observations"
)

echo "Pruning chunks older than ${RETENTION_MONTHS} months from ${#HYPERTABLES[@]} hypertables..."

for table in "${HYPERTABLES[@]}"; do
  echo "  ${table}..."
  if ! psql "$PSQL_URL" -v ON_ERROR_STOP=1 -t -c \
    "SELECT drop_chunks('${table}', older_than => INTERVAL '${RETENTION_MONTHS} months');" \
    2>/tmp/cleanup-err.$$; then
    if grep -qi "is not a hypertable\|function drop_chunks.*does not exist" /tmp/cleanup-err.$$; then
      echo "    skipped -- not a TimescaleDB hypertable on this instance"
    else
      echo "    failed:" >&2
      cat /tmp/cleanup-err.$$ >&2
      rm -f /tmp/cleanup-err.$$
      exit 1
    fi
  fi
  rm -f /tmp/cleanup-err.$$
done

echo "Cleanup complete."
