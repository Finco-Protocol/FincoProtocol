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

# P0-C: production is always the secure app mode. Checked here (not only in app/auth.py) so a
# misconfiguration exits with a typed status before any worker is spawned. No values are printed.
if [[ "${FINCO_APP_MODE:-}" != "pilot" ]]; then
    echo "ERROR: FINCO_APP_MODE must be exactly 'pilot' for the production launcher" >&2
    exit 78
fi

if [[ "$FINCO_SECRET_KEY" == "changeme"* ]]; then
    echo "ERROR: FINCO_SECRET_KEY is still a placeholder value" >&2
    exit 78
fi

if [[ "${FINCO_ADMIN_PASSWORD:-}" == "changeme"* ]]; then
    echo "ERROR: FINCO_ADMIN_PASSWORD is still a placeholder value" >&2
    exit 78
fi

# Application-level startup validation (secrets, admin credential, cookie policy, model execution
# configuration) runs BEFORE uvicorn forks workers, so a bad configuration fails once and typed.
# The interpreter is resolved below; this check is repeated after PYTHON_BIN is known.

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

if ! "$PYTHON_BIN" -c 'import app.auth' >/dev/null 2>&1; then
    echo "ERROR: secure startup validation failed (see FINCO_APP_MODE, FINCO_SECRET_KEY, FINCO_ADMIN_*, FINCO_COOKIE_SECURE); values are never printed" >&2
    exit 78
fi

exec "$PYTHON_BIN" -m uvicorn main_web:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --timeout-graceful-shutdown "$GRACEFUL_SHUTDOWN" \
    --access-log
