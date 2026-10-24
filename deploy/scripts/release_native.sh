#!/usr/bin/env bash
# FINCO native Run kernels (V10 Stage 1 + Stage 2, V11 Stage 3): the production release transaction, at DEPLOY time
# (never during a Model Run).
#
#   deploy/scripts/release_native.sh [install|verify|remove]     (default: install)
#
# install  builds the three kernels with the reviewed build scripts, requires the exact reviewed manifests (artifact
#          SHA-256, build ID, ABI, source SHA-256, compiler, flags, target), installs them atomically, verifies them
#          through the production loaders with an exact replay self-test, requires the installed finco-web unit to load
#          /opt/finco_protocol/.env.native, and only then writes that activation file (permanent production
#          activation, build-ID pinned, no secrets; .env is never touched). Any failure installs nothing, removes old
#          kernels and the activation file, and exits non-zero: Runs stay canonical. Idempotent.
# verify   re-checks the installed kernels, the self-test, the unit and the exact activation file.
# remove   deletes the kernels and the activation file (canonical after the next restart).
#
# Run as the deploy user BEFORE (re)starting finco-web: at runtime the service tree is read-only (ProtectSystem=strict).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: production Python is unavailable at $PYTHON_BIN" >&2
    exit 70
fi

exec "$PYTHON_BIN" -m tools.native_release "${1:-install}"
