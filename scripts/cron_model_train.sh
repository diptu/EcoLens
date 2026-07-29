#!/bin/bash
# Persistent-host cron: monthly full retrain of the demand-forecasting
# model (`make model-train` -- train -> evaluate -> register ->
# promote-if-better, see core/cli.py::cmd_train). TODO.md's "Wire the
# monthly retrain schedule" item asks for "1st of every month at 00:00
# AEST" specifically, not just "once a month" -- host cron's own
# timezone is not something to trust (this host's local TZ isn't even
# AEST/AEDT, see `date '+%Z'`), and macOS cron doesn't honor a per-line
# `CRON_TZ=` the way Linux's cronie does. So the schedule is split in
# two: crontab fires this script every hour on day 1 of the month
# (`0 * 1 * *`), and the script itself gates on the *Australia/Sydney*
# wall-clock hour via `TZ=Australia/Sydney date` -- correct across
# AEST/AEDT DST transitions with zero manual UTC-offset math, and
# correct regardless of the host's own timezone. 23 of the 24 hourly
# invocations on day 1 are a one-line no-op; only the one where
# Sydney-local time reads 00:xx actually runs the training cycle.
#
# cron runs with a minimal environment (no PATH beyond /usr/bin:/bin,
# no shell profile sourced) -- every path below is absolute for
# exactly that reason (see cron_ingest_all.sh, same convention).

set -uo pipefail

REPO_ROOT="/Users/macbook/Project/personal/EcoLens"
LOG_DIR="$REPO_ROOT/services/data-pipeline/data/log"
LOG_FILE="$LOG_DIR/cron_model_train.log"
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

log "=== monthly model-train run start (Sydney-local hour 00 on day 1) ==="

if /usr/bin/make -C "$REPO_ROOT" model-train >>"$LOG_FILE" 2>&1; then
    log "=== monthly model-train run complete: ok ==="
    exit 0
else
    log "=== monthly model-train run complete: FAILED (see traceback above) ==="
    exit 1
fi
