#!/bin/bash
# Persistent-host cron: fetch all 5 live sources into the local DuckDB
# store. Meant to run every 15 minutes (see `crontab -l`) -- comfortably
# under the tightest freshness threshold WarehouseRunner's
# SourceFreshnessChecker enforces (45 min for AEMO NEM/WEM/
# OpenElectricity), so `cron_warehouse_incremental.sh` running shortly
# after always sees fresh data.
#
# Runs each source independently (not `make ingest-all`, whose
# dependency-chain stops at the first failing target) so one flaky
# source (a transient AEMO/BoM/OE outage) doesn't block the other four
# -- each source's own circuit breaker already handles its own
# retry/backoff; this script's job is just to not let one source's
# failure prevent the others from running.
#
# cron runs with a minimal environment (no PATH beyond /usr/bin:/bin,
# no shell profile sourced) -- every path below is absolute for
# exactly that reason.

set -uo pipefail

REPO_ROOT="/Users/macbook/Project/personal/EcoLens"
LOG_DIR="$REPO_ROOT/services/data-pipeline/data/log"
LOG_FILE="$LOG_DIR/cron_ingest.log"
mkdir -p "$LOG_DIR"

export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >>"$LOG_FILE"
}

log "=== ingest run start ==="

FAILED=()
for target in ingest-openelectricity ingest-aemo-nem ingest-aemo-wem ingest-bom ingest-holidays; do
    log "-> make $target"
    if ! /usr/bin/make -C "$REPO_ROOT" "$target" >>"$LOG_FILE" 2>&1; then
        log "   FAILED: $target (see traceback above)"
        FAILED+=("$target")
    else
        log "   ok: $target"
    fi
done

if [ ${#FAILED[@]} -eq 0 ]; then
    log "=== ingest run complete: all 5 sources ok ==="
    exit 0
else
    log "=== ingest run complete: ${#FAILED[@]} source(s) failed: ${FAILED[*]} ==="
    exit 1
fi
