#!/bin/bash
# Persistent-host cron: daily retrain of every (source, metric)
# IsolationForest anomaly model (`make train-anomaly-models` ->
# ecolens.ingestion.service.anomaly.isolation_forest.train_all, see
# scripts/train_anomaly_isolation_forest.py). Root TODO.md's Anomaly
# Detection section's v2 item asks for "daily, not monthly" -- far
# lighter and far more frequent than the demand-forecasting models' own
# monthly retrain (cron_model_train.sh) -- so this is its own, separate
# cron entry, not folded into that one.
#
# Same split-schedule/Sydney-wall-clock-gate pattern as
# cron_model_train.sh/cron_model_finetune.sh (see cron_model_train.sh's
# own comment for the full why host cron's own timezone can't be
# trusted) -- host cron fires this hourly, the script itself only
# actually runs the retrain at Sydney-local hour 00, correct across
# AEST/AEDT DST transitions with zero manual UTC-offset math. No
# day-of-month gate here (unlike those two scripts) -- this one is
# meant to fire every day, not monthly.
#
# cron runs with a minimal environment (no PATH beyond /usr/bin:/bin,
# no shell profile sourced) -- every path below is absolute for
# exactly that reason (see cron_ingest_all.sh, same convention).

set -uo pipefail

REPO_ROOT="/Users/macbook/Project/personal/EcoLens"
LOG_DIR="$REPO_ROOT/services/data-pipeline/data/log"
LOG_FILE="$LOG_DIR/cron_train_anomaly_models.log"
mkdir -p "$LOG_DIR"

export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >>"$LOG_FILE"
}

sydney_hour="$(TZ=Australia/Sydney date '+%H')"
if [ "$sydney_hour" != "00" ]; then
    # Not the top of the Sydney day yet -- quiet no-op, don't spam the log.
    exit 0
fi

log "=== daily anomaly-model retrain run start (Sydney-local hour 00) ==="

if /usr/bin/make -C "$REPO_ROOT" train-anomaly-models >>"$LOG_FILE" 2>&1; then
    log "=== daily anomaly-model retrain run complete: ok ==="
    exit 0
else
    log "=== daily anomaly-model retrain run complete: FAILED (see traceback above) ==="
    exit 1
fi
