#!/bin/bash

# Configuration: Change these dates or interval as needed (or pass them as arguments)
START_DATE="${1:-2026-07-11}"
END_DATE="${2:-2026-07-20 create safegards againest }"
POLL_INTERVAL="${3:-2}"
BASE_URL="http://127.0.0.1:8001/ingestion/historical"

# List of sources
# SOURCES=("bom" "aemo_nem" "aemo_wem" "openelectricity" "holidays")
SOURCES=("openelectricity")


echo "Starting historical data ingestion day-by-day with polling..."
echo "Date Range: $START_DATE to $END_DATE"
echo "Poll Interval: ${POLL_INTERVAL}s"
echo "--------------------------------------------------"

# Function to generate sequence of dates between start and end (inclusive)
generate_dates() {
    python3 -c "
import sys
from datetime import datetime, timedelta

start = datetime.strptime('$START_DATE', '%Y-%m-%d')
end = datetime.strptime('$END_DATE', '%Y-%m-%d')
delta = timedelta(days=1)

current = start
while current <= end:
    print(current.strftime('%Y-%m-%d'))
    current += delta
"
}

# Loop through each day in the date range first, then loop through sources for that day
for current_date in $(generate_dates); do
    echo "=================================================="
    echo "Processing Date: $current_date"
    echo "=================================================="

    for source in "${SOURCES[@]}"; do
        echo "-> Triggering ingestion for source: [ $source ] on $current_date..."
        
        # Send POST request for a single day (start_date and end_date set to current_date)
        POST_RESPONSE=$(curl -s -X 'POST' \
            "$BASE_URL?source=$source&start_date=$current_date&end_date=$current_date" \
            -H 'accept: application/json')
        
        # Extract job_id using python
        JOB_ID=$(echo "$POST_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('job_id', ''))" 2>/dev/null)
        
        if [ -z "$JOB_ID" ]; then
            echo "   ERROR: Failed to start job for [ $source ] on $current_date. Response was:"
            echo "   $POST_RESPONSE"
            echo "--------------------------------------------------"
            continue
        fi
        
        echo "   Job started successfully. Job ID: $JOB_ID"
        echo "   Polling for completion..."

        # Polling loop
        while true; do
            STATUS_RESPONSE=$(curl -s -X 'GET' \
                "$BASE_URL/$JOB_ID" \
                -H 'accept: application/json')
                
            STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null)
            
            echo "   Current status: $STATUS"
            
            # Configurable lag between status checks
            sleep "$POLL_INTERVAL"
            
            if [ "$STATUS" = "completed" ] || [ "$STATUS" = "success" ]; then
                echo "   [ $source ] finished successfully for $current_date!"
                break
            elif [ "$STATUS" = "failed" ] || [ "$STATUS" = "error" ]; then
                echo "   [ $source ] FAILED for $current_date with status: $STATUS"
                echo "   Details: $STATUS_RESPONSE"
                break
            fi
        done
        
        echo "--------------------------------------------------"
    done
done

echo "All daily ingestion tasks processed across all sources."