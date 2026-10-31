# PR #400 CI V3 parallel performance: root cause (measured vs inferred)

Scope: CI timing forensics only. No financial engine, input, result, solver, auth, persistence, coverage or expected value
is changed. Evidence was collected 2026-10-30 from GitHub runs, worker artifacts and local profiling. Raw artifacts were
downloaded by immutable artifact ID.

## 1. Old 90-minute run 41076288645 (head `cc302e4d`): MEASURED

Plan artifact 15:06Z. Worker artifacts: w0 15:44, w6 15:46, w1 15:51, w7 16:02, w4 16:12, w5 16:33. w2 (artifact
12994421945) and w3 (12993133679) stopped at `elapsed_ms` 5400944 / 5400823, `timed_out: true`, `os_exit_code: 137`.

| Worker | Completed tests before the 5400 s cut | In-flight test at the cut (inventory order) | Confidence |
|---|---|---|---|
| worker-2 | 2299 / 2731 | `tests/test_rc_institutional_workspaces_integration.py::test_joint_history_export_portfolio_and_workspace_are_read_only` | medium: assumes pytest ran in inventory (collection) order; `process.log` has no per-test names |
| worker-3 | 713 / 2892 | `tests/test_model_mutation_security_successor.py::test_d029_run_route_invariants_hold_and_each_negative_is_detected_without_byte_pins` | medium (same assumption) |

Cause (measured): governance tests were extremely slow, not deadlocked. The same worker-5 module set took **5036 s** of
pytest time in that run and **2292 s** on `966a7254`. The difference is concentrated in governance modules, e.g.
`test_model_react_overnight_b_governance` 1387→275 s, `test_financing_f3_junior_governance` 1217→391 s,
`test_wf07_revenue_governance` 653→205 s. Commit `160ccf3` (after `cc302e4`) removed one O(changed paths × cohort) loop
(WF-03 `exact_blobs_ok` re-evaluated about 95× per call). The worker-3 in-flight test is a governance mutation test that calls
`S.violations` repeatedly, which is consistent with this cause.

Already handled elsewhere, not a bottleneck: the run-attempt artifact mix-up of run 41099667692
(`docs/ci_v3/incidents/pr400_artifact_attempt/`).

## 2. Current head `966a7254`, run 41115403654: MEASURED

Details are in TIMING_LEDGER.md. Critical path: run created 19:27:29 → route 1.5 min → plan 4.75 min → workers
30.3–46.5 min (worker-4 is the slowest) → aggregate. Planned 2036 s of pytest per worker; measured 1681–2631 s
(total 17,399 s, mean 2175 s).

### Root cause A: governance cohort evaluation spawns ~10^5 `git` subprocesses per test (MEASURED)
cProfile of `tests/test_wf07_revenue_governance.py::test_exact_seven_content_pins_only` (366 s locally):
- 122,491 `subprocess.run` calls; 361 of 366 s inside 29 calls of `tests/fin_v2_cohorts.valid()`.
- `tests/wsv2_core_scope._ws2_allows` calls `fin_v2_wsv2_scope.exact_blobs_ok()` once per changed path: **2436 calls,
  about 160 s**. Same pattern as the one `160ccf3` fixed for WF-03, but not fixed for WS-2.
- `fin_v2_cohorts.valid()` asks each cohort's `allowed_path()` per changed path. Each call re-reads that cohort's manifest
  through `git`/file I/O (about 66,000 calls, about 150 s).
Governance-type modules (names containing governance/scope/successor/authority/_candidate) took **5939 s = 34%** of all
measured pytest time on this head.

### Root cause B: one indivisible test is the floor (MEASURED)
`tests/test_model_react_rcux_goal_seek_targets_v1.py::test_npv_with_a_saved_valuation_policy_is_solved_in_keur_and_equals_the_legacy_route`
took **1485 s** in its call phase (module total 1608 s; planned 1609 s). No whole-module schedule with any worker count can put
worker-0 below about 27 min of pytest. Making it faster means touching the NPV goal-seek solving path (application/financial
code) or the test's expected target, and both are out of scope here. It is recorded as a product performance observation that
needs its own owner-reviewed investigation.

### Planner accuracy (MEASURED)
Accepted-source weights match measured times for most large modules (goal_seek 1609/1608 s, finance_integrity 841/884 s).
Over-runs are spread out (about 20–40%) plus PR-added governance cost (e.g. `test_rcux_governance` 102→272 s). Wrong weights are
not the dominant cause.

## 3. Unverified hypotheses (bounded)
1. The old worker-2 in-flight test was slow for the same governance reason rather than a separate hang. Test: per-test
   heartbeat telemetry (FIX_AND_VALIDATION.md §3) on the next long run.
2. Variance between hosted runners (CPU steal) contributes part of the ±20–40% per-module noise. Test: compare the same module
   across two runs on one head.

## 4. Known limitations
Local profiling ran on a 4-core sandbox concurrently with other pytest processes, so absolute local seconds are inflated; ratios
(memo vs. baseline, same conditions) are the evidence. The time from run start to a green gate cannot be measured until one
fully green run exists on this head.
