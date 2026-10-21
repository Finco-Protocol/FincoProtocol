#!/usr/bin/env bash
# Reproduces the golden-flow order dependency on the ORIGINAL test and verifies the isolated precondition.
# usage: run.sh IMAGE SOURCE_DIR ORIGINAL_TEST_FILE OUTPUT_JSON
#   SOURCE_DIR          private tracked source at the executed commit (read-only), including .git
#   ORIGINAL_TEST_FILE  tests/test_golden_flow_correction_b.py exactly as on main before Phase 3B
# Every run uses a FRESH private copy, no network, a non-root user and no shared database.
set -uo pipefail
image="$1"; source="$2"; original="$3"; out="$4"
T=tests/test_golden_flow_correction_b.py
run() {  # run LABEL "setup shell" "pytest args"
  local label="$1" setup="$2" args="$3"
  docker run --rm --network=none --user 1001:1001 --cpus=3 -e HOME=/tmp/h -e CI=true -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    --tmpfs /tmp:rw,exec,size=3g --mount "type=bind,source=$source,target=/src,readonly" \
    --mount "type=bind,source=$original,target=/original.py,readonly" "$image" \
    sh -c "cp -a /src /tmp/w && cd /tmp/w && $setup python -m pytest -q -p no:cacheprovider -p pytest_asyncio.plugin -W ignore $args 2>&1 | tail -3 | tr '\n' '|'; ls app/data | tr '\n' ' ' | sed 's/^/ shared_db_files=/'" \
    | python3 -c "import json,sys;print(json.dumps({'label':'$label','output':sys.stdin.read().strip()}))"
}
{
  for i in 1 2 3; do run "original-fresh-$i" "cp /original.py $T;" "$T"; done
  for i in 1 2 3; do run "isolated-fixture-fresh-$i" "" "$T"; done
  run "isolated-fixture-repeated-twice-same-copy" "" "$T $T"
  ring="tests/test_p0c_secure_runtime.py tests/test_protocol_api_beta.py tests/test_v2_scenario_overrides.py tests/test_model_v2_persistence.py tests/test_demo_history_retention.py tests/test_gf_f05_scenario_freshness.py tests/test_gf_f03_compare_freshness.py tests/test_correction_b_home_claims.py"
  run "ring-golden-first" "" "$T $ring"
  run "ring-golden-last" "" "$ring $T"
  run "original-in-ring-golden-last" "cp /original.py $T;" "$ring $T"
} | python3 -c "import json,sys;json.dump([json.loads(l) for l in sys.stdin],open('$out','w'),indent=1)"
