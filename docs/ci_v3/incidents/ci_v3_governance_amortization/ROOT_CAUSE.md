# ROOT_CAUSE — CI V3 governance performance regression (#405 → #409 → #410)

Correction PR: `perf/ci-v3-governance-amortization-post410` (Draft; DO NOT MERGE — GPT-6 High is the independent reviewer).
All measurements below are reproducible from the commands listed in TIMING_LEDGER.md.

## 1. The regression, anchored in CI's own native JUnit artifacts

Per-test wall times were read from each run's `public-ci-v3-worker-*-attempt-1` artifact
(`execution/child/native.xml`). Worker job walls come from the GitHub Actions job timestamps.

| PR | Run | wf03 module cases | wf03 module wall | Slowest worker wall | wf03 worker |
|----|-----|-------------------|------------------|---------------------|-------------|
| #405 | 41174457140 | 174 | **12 s** (worker-5: 174 cases / 12 s) | 40.5 min | worker-5 |
| #409 | 41249085437 | 185 | **4,979 s** (worker-1: 185 cases / 4,979 s) | 131.1 min | worker-1 |
| #410 | 41372476713 | 185 | **10,145 s** (worker-0: 185 cases / 10,145 s) | 170.9 min | worker-0 |

- #410 worker-0 ran exactly 255 cases, of which all 185 wf03 cases sum to **10,145 s = 100 % of the worker's
  testcase time** (the other 70 cases are collection skips at 0 s). The module *is* the incident.
- Per-`test_every_owned_byte_and_missing_path_fail_closed[*]` case: ~62 s on #410, ~32 s on #409, <0.1 s on #405.
- The node set barely changed (174 → 185, the eleven added OWNED_PATHS); the cost per node exploded.
- #413 (run 41495823762, product stream, untouched here) shows the same shape: worker-0 holds the 185-node
  wf03 module while most workers carry thousands of nodes.

## 2. Source-level onset (first step change, per diff)

**#405 → #409** (diff `ebf1f151..b7bfc4ed` of `tests/wf03_lifecycle_scope.py`):

* `_historical_maps_ok` was changed from a set-membership check to a per-moved-pin delegation:
  `after[source]!=value and not ((source in OWNED_PATHS and after[source]==pins[source]) or _wf06a_repin(...))`.
  `_wf06a_repin` → `fin_v2_wf06a_scope.predecessor_repin` → `pins_exactly` → **a full WF-06A cohort validation per
  moved predecessor pin**.
* `_b1_layer_ok` was added; for every pin that is new or moved since the B1 base it calls `_int409_admits`
  → `fin_v2_integration_409_scope.admits_pin` / `WF06A.pins_exactly` — again **a full cohort validation per pin**
  (the INT seal is state-keyed, but each call still recomputes that state key).

**#409 → #410** (diff `b7bfc4ed..3e00acab`):

* `_exact_blobs_ok`'s per-pin byte check became
  `if any(_blob(_read(root,p,ref))!=sha and not _wf06b_supersedes(p,_blob(_read(root,p,ref)),root,ref) ...)`,
  where `_wf06b_supersedes` → `wf06b_scope.supersedes` → **a full WF-06B cohort validation per mismatched pin**.
* The same two bounded hooks (`_wf06b_supersedes`, `_wf06b_allows`) were added to the per-pin loops of the
  #409 seal (`fin_v2_integration_409_scope.py`), the WF-06A cohort (`fin_v2_wf06a_scope.py`) and eight older
  cohort modules (`fin_v2_{3,d01,r1,rcux,wsv2}_scope.py`, `wsv2_core_scope.py`, `wf04_scope.py`,
  `fin_v2_cohorts.py` registry users).
* WF-06B's own `exact_blobs_ok` had **no verdict memo of its own** outside a manually-entered `scoped()` call:
  every ask re-ran the whole cohort validation (manifest read, ancestor/tree checks, a 33-path `rev-parse`,
  `ls-tree -r`, a full `diff --name-only BASE`, ~49 file reads, ~50 stats).

## 3. Measured mechanism: one logical verification re-runs the downstream cohort >1,000 times

A read-only instrumentation of `subprocess.check_output` (harness in this PR's evidence, no behavior change)
on the merged-#410 tree measured **one** `F.exact_blobs_ok()` call:

```
F.exact_blobs_ok() #1: 896.05 s, 8,617 git spawns   (verdict True)
  2,056 × git ls-files --others            (INT state-key recomputes)
    916 × git rev-parse HEAD + git diff HEAD  (INT state-key recomputes)
  1,147 × git merge-base --is-ancestor
  1,143 × git diff --name-only
  1,117 × git rev-parse b7bfc4ed^{tree}    (WF-06B re-validated per moved pin)
  1,117 × git rev-parse b7bfc4ed:<path>×33 (WF-06B BASE re-checks)
```

i.e. **~1,117 full WF-06B cohort validations and ~916 INT state-key recomputes inside ONE logical check**.
This is an O(pins × full-cohort) nested-revalidation explosion, then repeated for every test node:

- 185 wf03 nodes × ~3 outer calls (exact + valid + matches→valid) × ~20 s/call (CI Linux, ≈2.4 ms/spawn × 8,617)
  ≈ 10,145 s — matches the JUnit total exactly.
- #409 had the WF-06A/INT delegation but no WF-06B hook: ~10 s/outer call → 4,979 s. The #410 hook roughly
  doubled the cascade (every moved pin in *every* layer re-ran WF-06B), producing the second step change.
- Environmental variance is ruled out as the cause: the module is the whole worker; the same worker-0 that
  ran #405's module in 12 s ran #410's in 10,145 s; the per-node costs above are CI's own artifacts.

## 4. The defect class

Not a new-test, worker-count or hardware problem. It is a **cache-scope miss**: the composed governance
system re-validates an entire immutable downstream cohort once per moved path instead of once per outer
operation, although within one outer governance call (single-threaded, no file written meanwhile) the
downstream verdict is a fixed function of the same immutable inputs. The repo already contains the two safe
primitives for fixing this — the call-scope memo (`scoped()`) and the full-state-keyed verdict cache
(`fin_v2_integration_409_scope.py::_state_key/_RESULTS`, added in commit `cddd5e0c` "make the seal cheap and
safely memoised") — but the per-pin loops of WF-03/WF-06A/INT and the standalone WF-06B cohort never used them
together. The fix applies exactly those two primitives; see SECURITY_EQUIVALENCE.md.

## 5. Fix and measured effect (same machine, same tree state, same harness)

| Measurement (identical hardware/tree) | Before | After |
|---|---|---|
| `F.exact_blobs_ok()` cold | 896.1 s / 8,617 spawns | **19.3 s / 127 spawns** |
| `F.exact_blobs_ok()` warm | 677.3 s / 8,266 spawns | **2.85 s / 21 spawns** |
| `F.valid()` | ~800 s / ~8,600 spawns | **3.08 s / 23 spawns** |
| Verdict on merged-#410 tree | True | **True (unchanged)** |

Predicted CI effect (to be confirmed by the one exact-head hosted run on the final PR head):
per outer call ≈ 20.7 s → ~0.1–0.7 s; wf03 module 10,145 s → low single-digit minutes (≈30–100×);
slowest worker bounded by the pre-regression regular-suite floor (~40–53 min, cf. #400/#405).

## 6. What this is not

- No test was skipped, excluded (`-k`), weakened, or had its expected outcome changed; the node inventory
  and every negative of PR #410 are retained (plus new cache-invalidation negatives).
- No timeout was extended; worker count unchanged; no governance authority moved into CI flags.
- No `financial_engine/`, `finco_core/`, `domain/`, workflow, engine or formula file is touched.
