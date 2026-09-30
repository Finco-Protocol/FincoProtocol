#!/usr/bin/env bash
# Canonical FINCO production ASGI launcher.
# systemd and CI intentionally invoke this same repository-provided command.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

required_vars=("FINCO_SECRET_KEY" "FINCO_ADMIN_USER" "FINCO_ADMIN_PASSWORD")
for var in "${required_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo "ERROR: required production configuration $var is not set" >&2
        exit 78
    fi
done

if [[ "$FINCO_SECRET_KEY" == "changeme"* ]]; then
    echo "ERROR: FINCO_SECRET_KEY is still a placeholder value" >&2
    exit 78
fi

HOST="${FINCO_WEB_HOST:-127.0.0.1}"
PORT="${FINCO_WEB_PORT:-8000}"
WORKERS="${FINCO_WEB_WORKERS:-2}"
GRACEFUL_SHUTDOWN="${FINCO_WEB_GRACEFUL_SHUTDOWN_SECONDS:-30}"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: production Python is unavailable at $PYTHON_BIN" >&2
    echo "Install the repository-declared dependencies into $PROJECT_ROOT/.venv before starting the service" >&2
    exit 70
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
    echo "ERROR: FINCO_WEB_PORT must be an integer from 1 to 65535" >&2
    exit 78
fi

if ! [[ "$WORKERS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: FINCO_WEB_WORKERS must be a positive integer" >&2
    exit 78
fi

if ! [[ "$GRACEFUL_SHUTDOWN" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: FINCO_WEB_GRACEFUL_SHUTDOWN_SECONDS must be a positive integer" >&2
    exit 78
fi

if ! "$PYTHON_BIN" -c 'import uvicorn' >/dev/null 2>&1; then
    echo "ERROR: uvicorn is unavailable in the production virtual environment" >&2
    echo "Install the repository-declared dependencies before starting the service" >&2
    exit 70
fi

exec "$PYTHON_BIN" -m uvicorn main_web:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --timeout-graceful-shutdown "$GRACEFUL_SHUTDOWN" \
    --access-log
