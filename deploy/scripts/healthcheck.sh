#!/bin/bash
# FINCO Model Healthcheck Script
# Usage: ./healthcheck.sh [base_url]
# Designed for: systemd ExecStartPost, cron, or external monitoring
# Exits 0 if healthy, 1 if not.

BASE_URL="${1:-http://127.0.0.1:8000}"

RESPONSE=$(curl -s -f -o /dev/null -w "%{http_code}" "${BASE_URL}/public-health")

if [[ "$RESPONSE" == "200" ]]; then
    exit 0
else
    echo "Healthcheck failed: /public-health returned $RESPONSE" >&2
    exit 1
fi