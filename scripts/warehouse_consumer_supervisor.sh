#!/bin/bash
# Supervises the RabbitMQ-driven warehouse event consumer
# (ecolens.warehouse.core.event_consumer_entrypoint) as an always-on
# daemon, using only crontab -- no launchd, matching this repo's
# earlier explicit choice of crontab over launchd for the ingestion/
# warehouse cron. Crontab itself only knows how to run periodic jobs
# that start and exit; it has no concept of "keep this process running
# forever," so this script provides that instead: check whether the
# consumer is actually running (PID file + a check that the PID's
# command still matches, in case of PID reuse across a reboot), and if
# not, start a fresh instance in the background.
#
# Install BOTH of these (see `crontab -l`):
#   @reboot        scripts/warehouse_consumer_supervisor.sh   (start on boot)
#   */5 * * * *    scripts/warehouse_consumer_supervisor.sh   (restart if it died)
#
# Deliberately not a hardened process supervisor -- no exponential
# backoff, no crash alerting. If the consumer is crash-looping, this
# just restarts it on the next 5-minute tick; data/log/
# warehouse_consumer.log will show the repeated start attempts.
#
# Calls `uv run` directly rather than `make warehouse-consumer`: `$!`
# after backgrounding needs to capture the PID of the actual
# long-running python process, and routing through an extra `make`
# layer risks that PID belonging to a short-lived intermediate process
# instead.

set -uo pipefail

REPO_ROOT="/Users/macbook/Project/personal/EcoLens"
SERVICE_DIR="$REPO_ROOT/services/data-pipeline"
LOG_DIR="$SERVICE_DIR/data/log"
PID_FILE="$LOG_DIR/warehouse_consumer.pid"
LOG_FILE="$LOG_DIR/warehouse_consumer.log"
ENTRYPOINT="ecolens.warehouse.core.event_consumer_entrypoint"
mkdir -p "$LOG_DIR"

export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >>"$LOG_FILE"
}

is_running() {
    local pid="$1"
    [[ -n "$pid" ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    # Guard against PID reuse (e.g. across a reboot) matching some
    # unrelated process by coincidence.
    ps -p "$pid" -o command= 2>/dev/null | grep -q "$ENTRYPOINT"
}

if [[ -f "$PID_FILE" ]]; then
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if is_running "$existing_pid"; then
        exit 0
    fi
    log "consumer not running (stale pid ${existing_pid:-none}) -- restarting"
else
    log "no pid file -- starting consumer for the first time"
fi

cd "$SERVICE_DIR"
nohup uv run --active python -m "$ENTRYPOINT" >>"$LOG_FILE" 2>&1 &
new_pid=$!
echo "$new_pid" >"$PID_FILE"
log "started consumer, pid=$new_pid"
