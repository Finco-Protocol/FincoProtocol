# TIMING_LEDGER — CI V3 governance amortisation correction

Machine and environment statements are explicit per block. Nothing in this ledger compares across hardware
without saying so. Predicted values are marked PREDICTED and are always separate from measured values.

## A. Hosted CI V3, exact heads (authoritative regression evidence)

Source: native JUnit inside each run's `public-ci-v3-worker-N-attempt-1` artifact (`execution/child/native.xml`)
+ GitHub job timestamps. Same suite (whole-module assignment, 8 workers), same runner fleet, same workflow.

| PR | Run id | wf03 node count | wf03 module wall | Slowest-worker job wall | Worker holding wf03 |
|----|--------|-----------------|------------------|--------------------------|---------------------|
| #400 | 41136031925 | (pre-#409 module) | — | ~52.9 min | — |
| #405 | 41174457140 | 174 | **12 s** | 40.5 min | worker-5 |
| #409 | 41249085437 | 185 | **4,979 s** | 131.1 min | worker-1 |
| #410 | 41372476713 | 185 | **10,145 s** | 170.9 min | worker-0 |
| #413 | 41495823762 | 185 (worker-0) / 68 (worker-1) | in progress at time of check | (product stream, untouched) | worker-0 |

Per-node cost of `test_every_owned_byte_and_missing_path_fail_closed[*]` (from the same JUnit files):
#405 < 0.1 s → #409 ≈ 30–32 s → #410 ≈ 61–64 s.

## B. Local single-call profile (one Windows 10 x64 machine, Python 3.12.10, git 2.54; read-only
instrumentation of `subprocess.check_output`; identical LF checkout of merged #410 tree; verdict True in all rows)

| Measurement | Before (main 3e00acab) | After (Correction A, scope-only) | Spawn reduction |
|---|---|---|---|
| `F.exact_blobs_ok()` cold | 896.05 s / 8,617 spawns | 26.09 s / 124 spawns | 69× |
| `F.exact_blobs_ok()` warm | 677.27 s / 8,266 spawns | 4.43 s / 23 spawns | 359× |
| `F.valid()` | ~800 s / ~8,600 spawns (est. from cold profile) | 4.92 s / 25 spawns | ~340× |
| `W.exact_blobs_ok()` standalone | ~0.9 s / ~7 spawns (pre-#410-shape) | 1.01 s / 5 spawns (full fresh evaluation) | n/a (no persistent cache by design) |
| `WF06A.exact_blobs_ok()` cold, standalone | ~110 s / ~700+ spawns (est. from #1 profile shares) | 78.8 s / 391 spawns | ~1.8× |
| `INT.exact_blobs_ok()` cold, standalone | ~2.3 s / 17 spawns (short-circuit tree) / full-cascade on merged tree included above | 60.5 s / 299 spawns | n/a (full validation once) |
| Composite `fin_v2_cohorts.valid()` | (previously ~1000+ spawns) | 16.7 s / 71 spawns | — |

An intermediate revision of this PR (never pushed) measured 19.3 s/127 cold and 2.85 s/21 warm with a
process-lifetime state-keyed verdict cache; that cache was REMOVED in Correction A (security first — see
SECURITY_EQUIVALENCE.md §0), so the rows above are the shipped design. The WF-06A/INT standalone rows include
their full first-time validations, which the WF-03 outer path enters once per outer call instead of >1,000
times; the governing comparison is the `F.*` rows and the hosted module wall.

## C. Local suite walls (same machine, same checkout protocol, `-p no:pytest_ethereum` only)

| Suite | Before (main worktree) | After (branch worktree) | Speed-up |
|---|---|---|---|
| tests/test_wf06b_scope.py | (measured; see run log) | (measured; see run log) | — |
| tests/test_wf03_lifecycle_scope.py | INFEASIBLE locally (~93 h projected from 8,617 spawns × ~370 outer calls × 104 ms) | (measured) | — |
| tests/test_fin_v2_integration_409_scope.py | (measured) | (measured) | — |
| tests/test_fin_v2_wf06a_scope.py | (measured) | (measured) | — |
| tests/test_ci_v3_outcome_reconciliation.py | (measured) | (measured) | — |

## D. Hosted CI V3 on the correction head

- Run 41543769701 (first revision of this PR, head dffe439): FAILED at `safety-and-smoke / plan` (job 125614860267,
  step "Full collection") — `tools.ci_v3_schema.ContractError: original nodes removed; reviewed reconciliation
  authority required: ['tests/test_wf06b_scope.py::test_missing_owned_path_fails_closed[docs/react_migration/wf06b_a_plus/GOVERNANCE_SUCCESSOR_PLAN.md]']`.
  Cause: adding four document paths to `wf06b_scope.OWNED_PATHS` shifted the `sorted(...)[:6]` slice of the
  missing-path negative, dropping one original baseline node from collection. Workers never launched; no
  throughput conclusion can be drawn from that run. Correction A pins the historical node set literally
  (zero removed IDs, verified by full-suite `--collect-only` diff) before re-running.
- Correction A head (this revision): PREDICTED per outer governance call on Linux ≈ 20.7 s → 0.1–0.7 s
  (spawn count 8,617 → 23–124 at ≈2.4 ms/spawn); PREDICTED wf03 module wall low single-digit minutes (≥30×);
  slowest worker bounded by the pre-regression regular-suite floor (~40–53 min, cf. #400 = 52.9 min).
  MEASURED: (to be appended from the exact-head run of this revision — worker job walls + wf03/wf06b JUnit
  module walls).

- PREDICTED per outer governance call on Linux: 20.7 s → 0.1–0.7 s (spawn count 8,617 → 21–127 at ≈2.4 ms/spawn).
- PREDICTED wf03 module wall: 10,145 s → low single-digit minutes (≥30×; ≥5× required).
- PREDICTED slowest worker: bounded by the pre-regression regular-suite floor (~40–53 min, cf. #400 = 52.9 min,
  #405 = 40.5 min) plus a few minutes of governance modules → goal ≤ 60 min; stretch ≤ 45 min depends on the
  regular suite, not on this correction.
- MEASURED: (to be filled from the exact-head run of this PR — worker job walls + wf03 module wall from the
  worker JUnit artifacts).

## E. Reproduction commands

```bash
# JUnit per-test extraction used for section A
gh api repos/Finco-Protocol/FincoProtocol/actions/artifacts/<worker-artifact-id>/zip > w.zip
python - <<'PY'
import xml.etree.ElementTree as ET
for tc in ET.parse('execution/child/native.xml').getroot().iter('testcase'):
    print(tc.get('time'), tc.get('classname'), tc.get('name'))
PY

# single-call profile (read-only; counts spawns, changes no verdict)
python -I profile_wf03.py <checkout>
```

## F. Outcome parity (same node ids and outcomes, before vs after)

Recorded in the run logs: before = `main` worktree (3e00acab), after = this branch. The only expected
differences are the six additive cache-invalidation negatives in `tests/test_wf06b_scope.py` and the
pre-existing Windows-only exec-bit limitation (`test_extra_tracked_extra_untracked_and_executable_paths_fail_closed`,
fails identically on `main` locally; passes on Linux CI).
