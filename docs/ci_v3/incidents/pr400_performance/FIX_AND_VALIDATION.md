# PR #400 CI V3 performance: fix and validation

Branch: `perf/ci-v3-critical-path-post-400` (based on PR #400 head `966a7254`). It is **not** merged into PR #400. It is meant as
a separate PR after #400 merges.

## 1. Implemented (root cause A, first hot spot)
`tests/wsv2_core_scope.py`: `fin_v2_wsv2_scope.exact_blobs_ok(root, ref)` is evaluated **once per outer
`exact_blobs_ok()` call** instead of once per changed path. A call-scope memo stack (`_WS2_SCOPE`) is pushed and popped
around the call, keyed by `(root, ref)`, holds no bytes and is never shared between calls. This is the same construction as
`WF03.scoped()` from commit `160ccf3`. The verdict per path is unchanged because the WS-2 exact check does not depend on the
path being judged.

Test written first, which fails on the old code:
`tests/test_wsv2_core_scope.py::test_the_ws2_exact_check_runs_once_per_outer_call_and_is_never_shared`
- old code: `AssertionError: assert (5 == 1)` (5 evaluations for 5 changed paths);
- patched: pass. It also proves that nothing is reused across outer calls, that memoised and unmemoised verdicts are identical,
  that nothing is memoised outside a call, and that a failing WS-2 check still refuses every path.

Measured effect (same sandbox, same conditions, scratch prototype equivalent to the patch):
`tests/test_wf07_revenue_governance.py::test_exact_seven_content_pins_only` **345.6 s → 195.5 s (−44%)**, still passing.

## 2. Integration requirement (why this is not in #400)
`tests/wsv2_core_scope.py` and `tests/test_wsv2_core_scope.py` are exact-blob governed (WF-03 manifest, wsv2_core manifest, and
via the downstream rule WF-04). The pins must be regenerated against the **post-#400 main** (the base this PR will have).
Pinning them now against `966a7254` would become stale as soon as #400 gets its remaining governance corrections. Until then
this branch's governance suites fail on the new blobs by design. Steps after #400 merges: branch from main, cherry-pick this
commit, update the owning manifests' `source_blobs` and add ledger rows for the two paths (with the same downstream-pin rule
WF-04 enforces), run `tests/test_wf03_lifecycle_scope.py tests/test_wsv2_core_scope.py tests/test_wf04_scope.py
tests/test_finval_f01_scope.py tests/test_rcux_governance.py` and the F01 workflow suite, then run exact-head CI once.

## 3. Proposed, not implemented (ranked by expected critical-path saving)
1. **Cohort manifest memo in `fin_v2_cohorts.valid()`** (about 150 s in the profiled test): memoise each cohort's
   `manifest(root, ref)` within one outer `valid()`/`matches()`/`protected_blobs()` call. It touches every cohort module (or
   a shared helper), so it has a larger governance blast radius. A separate reviewed patch with the same once-per-call test
   pattern.
2. **Flush-safe per-test heartbeat** (diagnostics only): append `nodeid,start_ns,end_ns` lines to the worker evidence folder
   from the existing pytest adapter. It survives a SIGKILL timeout, so a future cut-off worker names its in-flight test
   exactly instead of by inventory-order inference. No change to selection, outcome, environment fingerprint or cleanup.
3. **Goal-seek NPV test (1485 s)**: the dominant floor. Needs an owner-reviewed investigation of the NPV goal-seek solver cost
   (iteration count/bracketing). Not a CI change, and expected values must not be touched.
4. Not recommended: splitting `test_model_react_rcux_goal_seek_targets_v1.py` across workers (whole-module isolation is
   unproven, and its cost is a single test anyway), raising worker count (the floor dominates), or any timeout change.

## 4. Recommendation
`MERGE_400_UNCHANGED_THEN_PERF_PR`: performance does not block #400. A correct #400 run fits easily within the existing budget
(slowest worker 46.5 min of a 200-min job limit). #400 is currently blocked by three genuine governance-expectation failures,
which are unrelated to performance and are tracked by its owner.
