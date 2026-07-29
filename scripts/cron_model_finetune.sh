#!/bin/bash
# Persistent-host cron: monthly online fine-tune of all three production
# models (LSTM, TFT, TimesFM calibration head) -- `make
# model-online-finetune[-tft|-timesfm]`, each fine-tuning its own current
# "production" alias on just the 30-min data buffer accumulated since that
# version's own last_trained_at (root TODO.md's "Fine tuning" section),
# then gated by the usual promote_if_better check. Same
# split-schedule/Sydney-wall-clock-gate pattern as cron_model_train.sh (see
# that script's own comment for why) -- gated on day 15 instead of day 1
# specifically so this never fires on the same day as the full monthly
# retrain cron_model_train.sh already runs: a fine-tune immediately after a
# from-scratch retrain would have nothing meaningful in its "since last
# fine-tune" buffer yet, and would just burn a training cycle for no signal.
#
# cron runs with a minimal environment (no PATH beyond /usr/bin:/bin, no
# shell profile sourced) -- every path below is absolute for exactly that
# reason (see cron_ingest_all.sh/cron_model_train.sh, same convention).

set -uo pipefail

REPO_ROOT="/Users/macbook/Project/personal/EcoLens"
LOG_DIR="$REPO_ROOT/services/data-pipeline/data/log"
LOG_FILE="$LOG_DIR/cron_model_finetune.log"
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

log "=== monthly online-finetune run start (Sydney-local hour 00 on day 15) ==="

overall_status=0

for target in model-online-finetune model-online-finetune-tft model-online-finetune-timesfm; do
    log "--- $target start ---"
    if /usr/bin/make -C "$REPO_ROOT" "$target" >>"$LOG_FILE" 2>&1; then
        log "--- $target complete: ok ---"
    else
        log "--- $target complete: FAILED (see traceback above) ---"
        overall_status=1
    fi
done

if [ "$overall_status" -eq 0 ]; then
    log "=== monthly online-finetune run complete: ok ==="
else
    log "=== monthly online-finetune run complete: one or more targets FAILED ==="
fi

exit "$overall_status"
