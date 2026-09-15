#!/bin/bash
# FINCO Model Production Startup Script
# Usage: ./start_prod.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== FINCO Model Production Start ==="
echo "Project root: $PROJECT_ROOT"

# Check virtual environment
if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
    echo "ERROR: .venv not found at $PROJECT_ROOT/.venv"
    exit 1
fi

# Check environment file
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "ERROR: .env not found at $PROJECT_ROOT/.env"
    echo "Copy deploy/env.example to .env and configure it."
    exit 1
fi

# Check required env vars
required_vars=("FINCO_SECRET_KEY" "FINCO_ADMIN_USER" "FINCO_ADMIN_PASSWORD")
for var in "${required_vars[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo "ERROR: $var is not set in .env"
        exit 1
    fi
done

# Validate secret key is not the placeholder
if [[ "$FINCO_SECRET_KEY" == "changeme"* ]]; then
    echo "ERROR: FINCO_SECRET_KEY is still the placeholder value."
    echo "Generate a real key with: python3 -c \"import secrets; print(secrets.token_hex(64))\""
    exit 1
fi

echo "Environment validated."

# Start the service via systemd
echo "Starting finco-web service..."
sudo systemctl start finco-web

echo "=== FINCO Model started ==="
echo "Service status:"
sudo systemctl status finco-web --no-pager -l || true