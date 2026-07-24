#!/bin/bash
# Append a new tagged TODO to the root TODO.md.
#
# Usage: scripts/add_todo.sh "<description>" [service]
#   service: forecast-api | data-pipeline | dashboard (optional)
#
# Auto-assigns the next sequential [ECO-NNN] id (scanning every TODO.md in
# the repo for the current max). If `service` names a known "## Service: X"
# section, the bullet is inserted there (tag only, no redundant service
# prefix — the section already says it); otherwise it goes under
# "## 🚀 Priority (Immediate)" with an inline `service` tag so it's still
# identifiable when mixed with other services.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TODO_FILE="$ROOT_DIR/TODO.md"
PRIORITY_HEADING="## 🚀 Priority (Immediate)"

DESC="${1:-}"
SVC="${2:-}"

if [ -z "$DESC" ]; then
    echo "Usage: make todo DESC=\"description\" [SVC=forecast-api|data-pipeline|dashboard]" >&2
    exit 1
fi
if [ ! -f "$TODO_FILE" ]; then
    echo "Error: $TODO_FILE not found." >&2
    exit 1
fi

case "$SVC" in
    forecast-api)  HEADING="## 🏗 Service: Forecast API" ;;
    data-pipeline) HEADING="## 📊 Service: Data Pipeline" ;;
    dashboard)     HEADING="## 🛠 Service: Dashboard" ;;
    "")            HEADING="$PRIORITY_HEADING" ;;
    *)
        echo "⚠️  Unknown SVC '$SVC' — filing under Priority instead. Known: forecast-api, data-pipeline, dashboard." >&2
        HEADING="$PRIORITY_HEADING"
        ;;
esac

# Next sequential numeric ECO-id, scanning every TODO.md in the repo.
LAST_ID=$(grep -rhoE '\[ECO-[0-9]+\]' "$ROOT_DIR"/TODO.md "$ROOT_DIR"/services/*/TODO.md 2>/dev/null \
    | grep -oE '[0-9]+' \
    | sort -n \
    | tail -1)
NEXT_ID=$(( ${LAST_ID:-100} + 1 ))
TAG="[ECO-$NEXT_ID]"

# Trim leading/trailing whitespace, capitalise the first letter, ensure a
# trailing period. (Capitalisation uses awk, not sed's \U — that's a GNU
# extension and macOS ships BSD sed, which doesn't support it.)
DESC="$(printf '%s' "$DESC" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
DESC="$(printf '%s' "$DESC" | awk '{ print toupper(substr($0,1,1)) substr($0,2) }')"
case "$DESC" in
    *.) ;;
    *) DESC="$DESC." ;;
esac

if [ "$HEADING" = "$PRIORITY_HEADING" ] && [ -n "$SVC" ]; then
    LINE="- [ ] $TAG \`$SVC\`: $DESC"
else
    LINE="- [ ] $TAG $DESC"
fi

awk -v line="$LINE" -v heading="$HEADING" '
    $0 == heading { print; in_sec = 1; next }
    in_sec && /^$/ { print line; print; in_sec = 0; inserted = 1; next }
    { print }
    END { if (!inserted) print line }
' "$TODO_FILE" >"$TODO_FILE.tmp" && mv "$TODO_FILE.tmp" "$TODO_FILE"

echo "✅ Added $TAG to $TODO_FILE"
echo "   $LINE"
