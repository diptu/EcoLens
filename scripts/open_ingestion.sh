#!/bin/bash

# Configuration: Change these dates or interval as needed (or pass them as arguments)
START_DATE="${1:-2026-06-14}"
END_DATE="${2:-2026-06-20}"
POLL_INTERVAL="${3:-2}"
BASE_URL="http://127.0.0.1:8001/ingestion/historical"

# List of sources
# SOURCES=("bom" "aemo_nem" "aemo_wem" "openelectricity" "holidays")
SOURCES=("openelectricity")

# Maximum attempts/timeouts for polling to prevent infinite loops (e.g., 300 checks = 10 minutes at 2s interval)
MAX_POLL_ATTEMPTS=300

echo "Starting historical data ingestion day-by-day with polling and safeguards..."
echo "Date Range: $START_DATE to $END_DATE"
echo "Poll Interval: ${POLL_INTERVAL}s"
echo "--------------------------------------------------"

# Function to validate date string format (YYYY-MM-DD)
validate_date() {
    local date_str="$1"
    if ! python3 -c "from datetime import datetime; datetime.strptime('$date_str', '%Y-%m-%d')" 2>/dev/null; then
        echo "ERROR: Invalid date format '$date_str'. Expected YYYY-MM-DD." >&2
        exit 1
    fi
}

# Validate inputs upfront
validate_date "$START_DATE"
validate_date "$END_DATE"

# Function to generate sequence of dates between start and end (inclusive) with validation
generate_dates() {
    python3 -c "
import sys
from datetime import datetime, timedelta

try:
    start = datetime.strptime('$START_DATE', '%Y-%m-%d')
    end = datetime.strptime('$END_DATE', '%Y-%m-%d')
    
    if start > end:
        print('ERROR: START_DATE cannot be after END_DATE.', file=sys.stderr)
        sys.exit(1)
        
    delta = timedelta(days=1)
    current = start
    while current <= end:
        print(current.strftime('%Y-%m-%d'))
        current += delta
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
}

# Capture date generation and handle potential script exit if validation fails
DATE_LIST=$(generate_dates)
if [ $? -ne 0 ]; then
    echo "$DATE_LIST"
    exit 1
fi

# Loop through each day in the date range first, then loop through sources for that day
for current_date in $DATE_LIST; do
    echo "=================================================="
    echo "Processing Date: $current_date"
    echo "=================================================="

    for source in "${SOURCES[@]}"; do
        echo "-> Triggering ingestion for source: [ $source ] on $current_date..."
        
        # Send POST request with error handling for network/curl failures
        POST_RESPONSE=$(curl -s -S --fail-with-body -X 'POST' \
            "$BASE_URL?source=$source&start_date=$current_date&end_date=$current_date" \
            -H 'accept: application/json')
        
        CURL_EXIT_CODE=$?
        if [ $CURL_EXIT_CODE -ne 0 ]; then
            echo "   ERROR: HTTP request failed for [ $source ] on $current_date (Curl exit code: $CURL_EXIT_CODE)."
            echo "--------------------------------------------------"
            continue
        fi
        
        # Extract job_id safely using python with JSON decode error handling
        JOB_ID=$(echo "$POST_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('job_id', ''))
except Exception:
    print('')
" 2>/dev/null)
        
        if [ -z "$JOB_ID" ]; then
            echo "   ERROR: Failed to parse job_id for [ $source ] on $current_date. Response was:"
            echo "   $POST_RESPONSE"
            echo "--------------------------------------------------"
            continue
        fi
        
        echo "   Job started successfully. Job ID: $JOB_ID"
        echo "   Polling for completion..."

        # Polling loop with safeguards
        ATTEMPT_COUNT=0
        JOB_FAILED=false
        
        while true; do
            ATTEMPT_COUNT=$((ATTEMPT_COUNT + 1))
            
            if [ "$ATTEMPT_COUNT" -gt "$MAX_POLL_ATTEMPTS" ]; then
                echo "   [ $source ] TIMEOUT: Exceeded maximum poll attempts ($MAX_POLL_ATTEMPTS) for $current_date."
                JOB_FAILED=true
                break
            fi

            STATUS_RESPONSE=$(curl -s -S --fail-with-body -X 'GET' \
                "$BASE_URL/$JOB_ID" \
                -H 'accept: application/json')
                
            if [ $? -ne 0 ]; then
                echo "   WARNING: Status check request failed temporarily. Retrying in ${POLL_INTERVAL}s..."
                sleep "$POLL_INTERVAL"
                continue
            fi
                
            STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('status', 'unknown'))
except Exception:
    print('unknown')
" 2>/dev/null)
            
            echo "   Current status (Attempt $ATTEMPT_COUNT/$MAX_POLL_ATTEMPTS): $STATUS"
            
            if [ "$STATUS" = "completed" ] || [ "$STATUS" = "success" ]; then
                echo "   [ $source ] finished successfully for $current_date!"
                break
            elif [ "$STATUS" = "failed" ] || [ "$STATUS" = "error" ]; then
                echo "   [ $source ] FAILED for $current_date with status: $STATUS"
                echo "   Details: $STATUS_RESPONSE"
                JOB_FAILED=true
                break
            fi
            
            # Configurable lag between status checks
            sleep "$POLL_INTERVAL"
        done
        
        if [ "$JOB_FAILED" = true ]; then
            echo "   Skipping remaining steps for this task due to failure."
        fi
        
        echo "--------------------------------------------------"
    done
done

echo "All daily ingestion tasks processed across all sources."