#!/bin/bash
# Universal Monorepo TODO Auditor

# Get the absolute path of the root directory
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICES=("forecast-api" "data-pipeline")

for svc in "${SERVICES[@]}"; do
    ROOT_SVC="$ROOT_DIR/services/$svc"
    TODO_FILE_ROOT="$ROOT_SVC/TODO.md"
    TODO_FILE_DOCS="$ROOT_SVC/docs/TODO.md"
    SOURCE_DIR="$ROOT_SVC/src"

    # Identify TODO file
    if [ -f "$TODO_FILE_ROOT" ]; then
        TODO_FILE="$TODO_FILE_ROOT"
    elif [ -f "$TODO_FILE_DOCS" ]; then
        TODO_FILE="$TODO_FILE_DOCS"
    else
        echo "⚠️  Skipping $svc: No TODO.md found in $ROOT_SVC or $ROOT_SVC/docs/."
        continue
    fi

    echo "🔍 Auditing TODOs in $svc..."
    
    # 1. Extract IDs: Find any text inside square brackets (e.g., [ECO-123])
    # 2. -r: Recursive search
    # 3. -o: Only matching the pattern
    # 4. -h: Hide filenames (we just want the IDs)
    # 5. Regex explanation: \[([A-Z0-9-]+)\] matches [TAG-123] and captures the content
    IDS=$(grep -rhE "\[[A-Z0-9-]+\]" "$SOURCE_DIR" 2>/dev/null | grep -oE "[A-Z0-9-]+" | sort -u)

    # DEBUG: See what the script found
    if [ -z "$IDS" ]; then
        echo "   No TODO tags found in code."
    else
        echo "   Found IDs in code: $(echo $IDS | tr '\n' ' ')"
    fi

    # Audit each ID against the TODO.md
    for id in $IDS; do
        if ! grep -q "$id" "$TODO_FILE"; then
            echo "⚠️  WARNING: Orphan TODO $id found in $svc/src, but missing from $TODO_FILE"
        fi
    done
done
echo "✅ Audit complete."