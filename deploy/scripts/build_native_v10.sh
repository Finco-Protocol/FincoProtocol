#!/usr/bin/env bash
# FINCO V10 native kernels: offline build + verification at DEPLOY time (never during a Model Run).
#
#   deploy/scripts/build_native_v10.sh [install|verify|remove]     (default: install)
#
# install  builds both kernels with the reviewed build scripts, requires the exact reviewed manifests
#          (artifact SHA-256, build ID, ABI, compiler, flags, target), installs them atomically and verifies
#          them through the production loaders. Any mismatch installs nothing and removes old kernels.
# remove   deletes the kernels: every Run is served by canonical Python.
#
# Run as the deploy user BEFORE (re)starting finco-web: at runtime the service tree is read-only
# (ProtectSystem=strict). Activation itself is a separate setting (FINCO_NATIVE_V10_RUN, default off).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: production Python is unavailable at $PYTHON_BIN" >&2
    exit 70
fi

exec "$PYTHON_BIN" -m tools.native_v10_release "${1:-install}"
