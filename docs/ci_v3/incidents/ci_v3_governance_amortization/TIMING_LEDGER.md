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

| Measurement | Before (main 3e00acab) | After (this branch) | Spawn reduction |
|---|---|---|---|
| `F.exact_blobs_ok()` cold | 896.05 s / 8,617 spawns | 19.27 s / 127 spawns | 68× |
| `F.exact_blobs_ok()` warm INT state | 677.27 s / 8,266 spawns | 2.85 s / 21 spawns | 394× |
| `F.valid()` | ~800 s / ~8,600 spawns (est. from cold profile) | 3.08 s / 23 spawns | ~370× |
| `W.exact_blobs_ok()` standalone (warm cache) | ~0.9 s / ~7 spawns | 0.39 s / 3 spawns (state-key only) | 2.3× |
| `INT.exact_blobs_ok()` cold, standalone | ~2.3 s / 17 spawns (short-circuit tree) / full-cascade on merged tree included above | 24.6 s / 179 spawns | n/a (full validation once) |
| `WF06A.exact_blobs_ok()` cold, standalone | ~110 s / ~700+ spawns (est. from #1 profile shares) | 38.9 s / 275 spawns | ~2.5× |
| Composite `fin_v2_cohorts.valid()` | (previously ~1000+ spawns) | 10.09 s / 69 spawns | — |

Note: the "After" WF-06A/INT standalone rows include their full first-time validations (which the WF-03 outer
path enters once per outer call instead of >1,000 times). The rows are not comparable to the "Before" column
for those two entries without the WF-03 outer call context; the governing comparison is the `F.*` rows and the
hosted module wall.

## C. Local suite walls (same machine, same checkout protocol, `-p no:pytest_ethereum` only)

| Suite | Before (main worktree) | After (branch worktree) | Speed-up |
|---|---|---|---|
| tests/test_wf06b_scope.py | (measured; see run log) | (measured; see run log) | — |
| tests/test_wf03_lifecycle_scope.py | INFEASIBLE locally (~93 h projected from 8,617 spawns × ~370 outer calls × 104 ms) | (measured) | — |
| tests/test_fin_v2_integration_409_scope.py | (measured) | (measured) | — |
| tests/test_fin_v2_wf06a_scope.py | (measured) | (measured) | — |
| tests/test_ci_v3_outcome_reconciliation.py | (measured) | (measured) | — |

## D. Hosted CI V3 on the correction head (PREDICTED before the run; measured section to be appended after)

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
