#!/usr/bin/env bash
# Model CI "acceptance" job: the Chromium acceptance scripts that are run as programs (not pytest modules).
# Each runs in its own process and both always run; any non-zero exit fails the job.
set -uo pipefail
OUT="${1:-evidence/acceptance}"
mkdir -p "$OUT"
rc=0
for module in tests.model_outputs_workspace_acceptance tests.model_statements_tree_acceptance; do
  echo "::group::$module"
  python -m "$module" --out "$OUT/${module##*.}" || { echo "FAILED: $module"; rc=1; }
  echo "::endgroup::"
done
exit $rc
