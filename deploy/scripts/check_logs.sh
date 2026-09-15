#!/usr/bin/env bash
# check_logs.sh — FINCO Model ops log check
# Usage: ./check_logs.sh [--errors-only] [--last=N]

set -euo pipefail

MODE="${1:-summary}"
LINES="${2:-50}"

LOGDIR="${FINCO_LOG_DIR:-/var/log/finco-web}"

echo "=== FINCO Model Log Check ==="
echo "Log dir: $LOGDIR"
echo ""

if [[ ! -d "$LOGDIR" ]]; then
    echo "WARNING: Log directory $LOGDIR does not exist"
    exit 0
fi

if [[ "$MODE" == "--errors-only" ]]; then
    echo "--- Recent errors ---"
    grep -r "ERROR\|CRITICAL\|Exception\|Traceback" "$LOGDIR"/*.log 2>/dev/null | tail -20 || echo "No errors found"
elif [[ "$MODE" == "--last" ]]; then
    echo "--- Last $LINES lines of all logs ---"
    for f in "$LOGDIR"/*.log; do
        [[ -f "$f" ]] || continue
        echo "=== $(basename $f) ==="
        tail -$LINES "$f"
    done
else
    echo "--- Error summary ---"
    ERROR_COUNT=$(grep -r "ERROR\|CRITICAL" "$LOGDIR"/*.log 2>/dev/null | wc -l || echo 0)
    echo "Total error lines: $ERROR_COUNT"
    
    echo ""
    echo "--- Access log (last 20 non-health) ---"
    cat "$LOGDIR/access.log" 2>/dev/null | grep -v "public-health\|healthcheck" | tail -20 || echo "No access log"

    echo ""
    echo "--- Recent warnings ---"
    grep "WARNING\|SLOW" "$LOGDIR"/*.log 2>/dev/null | tail -10 || echo "No warnings"

    echo ""
    echo "--- Service status ---"
    systemctl is-active finco-web 2>/dev/null || echo "systemctl not available"
fi