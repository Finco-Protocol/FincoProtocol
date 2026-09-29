#!/bin/bash
# FINCO Model Production Startup Script
# Usage: ./start_prod.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== FINCO Model Production Start ==="
echo "Project root: $PROJECT_ROOT"

# Check virtual environment
if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    echo "ERROR: production Python not found at $PROJECT_ROOT/.venv/bin/python" >&2
    exit 1
fi

# systemd loads this file through EnvironmentFile; run_web.sh validates the
# mandatory variable names after loading. This helper never prints secret values.
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "ERROR: .env not found at $PROJECT_ROOT/.env" >&2
    echo "Copy deploy/env.example to .env and configure it." >&2
    exit 1
fi

if [[ ! -f "$PROJECT_ROOT/deploy/scripts/run_web.sh" ]]; then
    echo "ERROR: canonical production launcher is missing" >&2
    exit 1
fi

echo "Starting finco-web service..."
sudo systemctl start finco-web

# Bounded startup/health wait. The service must remain active while the public
# health endpoint becomes available.
for _ in $(seq 1 20); do
    if ! sudo systemctl is-active --quiet finco-web; then
        echo "ERROR: finco-web exited during startup" >&2
        sudo systemctl status finco-web --no-pager -l || true
        exit 1
    fi

    if /bin/bash "$PROJECT_ROOT/deploy/scripts/healthcheck.sh" >/dev/null 2>&1; then
        echo "=== FINCO Model started ==="
        sudo systemctl status finco-web --no-pager -l || true
        exit 0
    fi
    sleep 1
done

echo "ERROR: finco-web did not pass /public-health within the bounded startup period" >&2
sudo systemctl status finco-web --no-pager -l || true
exit 1
