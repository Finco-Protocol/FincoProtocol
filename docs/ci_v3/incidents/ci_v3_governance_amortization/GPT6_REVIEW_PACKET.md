# GPT6_REVIEW_PACKET — CI V3 governance amortisation correction (Draft PR, DO NOT MERGE)

Independent reviewer: GPT-6 High. This packet links every claim to a checkable artifact; nothing is
cherry-picked — the failing/negative rows are included wherever they exist.

## 1. What to review

- Branch: `perf/ci-v3-governance-amortization-post410` (from `main` @ `3e00acab71ea4c2bd9e7396e5bee609225212623`)
- Draft PR: <PR URL — filled at handover>
- Diff (5 files + 4 new documents):
  - `tests/wf06b_scope.py` — full-state-keyed verdict cache (`_state_key`/`_cached_exact`, the verbatim PR-#409-seal construction) + shared `scoped()`
  - `tests/wf03_lifecycle_scope.py` — `_downstream_scopes()` entered by `exact_blobs_ok`/`valid`/`scoped()` (composite-registry behaviour for standalone calls); **no** state cache at this layer
  - `tests/fin_v2_wf06a_scope.py` — shared `scoped()` only (no state cache: its negatives monkeypatch its `_read`)
  - `tests/fin_v2_integration_409_scope.py` — shared `scoped()` only
  - `tests/test_wf06b_scope.py` — six additive cache-invalidation negatives; nothing else touched
  - `docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json` — re-pins of exactly the five edited files + `validation` note
  - four new documents under `docs/react_migration/wf06b_a_plus/` (each added as a literal path to `wf06b_scope.TEST_AND_DOC_PATHS`)
- Evidence documents: ROOT_CAUSE / TIMING_LEDGER / SECURITY_EQUIVALENCE (same directory).

## 2. Exact links

- Regression runs: #405 run 41174457140 (wf03: worker-5, 174 cases / 12 s),
  #409 run 41249085437 (wf03: worker-1, 185 / 4,979 s), #410 run 41372476713 (wf03: worker-0, 185 / 10,145 s —
  100 % of worker-0's testcase time), #413 run 41495823762 (product stream, untouched).
- Correction run: <exact-head run id + worker walls — filled after the single hosted validation>.
- Diff of the onset commits: `git diff ebf1f151 b7bfc4ed -- tests/wf03_lifecycle_scope.py` (adds `_wf06a_repin`,
  `_int409_admits`, `_b1_layer_ok`, historical-map delegation) and `git diff b7bfc4ed 3e00acab` (adds the
  `_wf06b_supersedes`/`_wf06b_allows` hooks to WF-03, the #409 seal, WF-06A and eight older cohorts).
- Precedent for the cache construction: commit `cddd5e0c` "PR #409: make the seal cheap and safely memoised
  (F01 exceeded the 25 min job limit)" — `fin_v2_integration_409_scope._state_key/_RESULTS`.
- Local profile logs: `profile_run1.log` (before), harness script (read-only spawn counter; changes no verdict).

## 3. Test commands actually run

```bash
python -m pytest tests/test_wf06b_scope.py tests/test_wf03_lifecycle_scope.py \
  tests/test_fin_v2_integration_409_scope.py tests/test_fin_v2_wf06a_scope.py \
  tests/test_ci_v3_outcome_reconciliation.py -q -rf        # correction tree
git worktree add --detach <wt> 3e00acab && <same command>  # baseline tree, outcome parity
python -I profile_wf03.py <checkout>                        # single-call spawn/time profile
```
(Local-only plugin suppression `-p no:pytest_ethereum` was needed on this Windows machine because the global
site-packages ship a broken `web3` pytest plugin; CI environments are unaffected.)

## 4. Security-equivalence claims to challenge

1. The WF-06B state key covers every mutable input the verdict depends on. *Challenge: find an input the
   verdict reads that the key does not cover (staged bytes? mode? symlink? untracked bytes? manifest? identity
   constants?).*
2. No verdict is reused across different bytes or different roots; the memo never outlives one outer call at
   the WF-03/WF-06A/INT layers, and at the WF-06B layer is keyed by full state.
3. Every PR-#410 negative still fails closed, with real bytes in disposable worktrees; the six new negatives
   cover same-process mutation-after-success, restore-then-different-mutation, staged index, untracked
   evidence vs untracked source, forged identity constant after a warm verdict, per-root separation, and
   shared-scope amortisation with restores.
4. No protected surface (`financial_engine/`, `finco_core/`, `domain/`, `.github/`, `tools/`, `main_web.py`,
   frontend) is modified; the only manifest changes are the five re-pinned blobs and the validation note.
5. The governance successor procedure is followed exactly as #410 did (literal pins; older manifests untouched;
   supersession hooks accept the five moved governance files).

## 5. Questions the independent reviewer should press

1. **Cache correctness**: `_state_key` hashes `git diff HEAD --binary` + untracked names/bytes. Is there any
   state the WF-06B `_exact_blobs_ok` reads that this key misses — e.g. `.gitmodules`-style indirection, worktree
   shared-object mutations, or reflog/HEAD races within one outer call?
2. **Mid-scope mutation window**: inside one outer call a real byte flip is (documentedly) masked by the scope
   memo until the call returns. The composite registry has always had this property. Is one outer governance
   call the right trust boundary here, and are all callers of the per-path hooks single-threaded?
3. **Negative masking via restores**: a test that restores byte-exact state legitimately re-uses the cached
   True. Could any *production* caller mutate and restore bytes within one process in a way that should
   invalidate a verdict but does not change the key?
4. **`_RESULTS` bound**: entries clear wholesale at >64 (PR-#409 seal pattern). Is a wholesale clear acceptable,
   or should this be LRU? Any denial-of-service angle on a hostile untracked-file set (hashing cost)?
5. **Untracked hashing cost**: on CI, generated `evidence/` files grow during a run; each state change forces a
   re-validation (fresh full cohort check). Is the added re-validation cost on evidence-heavy runs bounded?
6. **Scope sharing semantics**: nested `scoped()` now shares the outermost memo. Is there any caller that
   entered `scoped()` expecting a *fresh* memo for a nested region (the W test `test_no_result_outlives...`
   documents the outer semantics)? We found none; please re-verify across all cohorts.
7. **WF-03 layer has no state cache** (deliberate: its negatives monkeypatch `F._read`/`F._git`). Is the
   remaining per-outer-call cost (~21–127 spawns) acceptable, or should further amortisation be pursued in a
   later bounded change?
8. **Older cohorts untouched**: `fin_v2_{3,d01,r1,rcux,wsv2}_scope.py`/`wsv2_core_scope.py`/`wf04_scope.py`
   still run their per-pin WF-06B hooks; they now hit the WF-06B state cache (~3 spawns/ask instead of a full
   validation). Is the residual cost acceptable, or should the same downstream-scope entry be extended to them
   in a follow-up?
9. **Manifest re-pin authority**: the correction re-pins five governance files in the WF-06B manifest under the
   task authorization (bounded CI performance correction). Is that within the WF06B-D3 decision's letter, or
   does it need a fresh Owner decision line in the manifest's `authorization` field?
10. **Performance acceptance**: the hosted gate is slowest-worker ≤ 60 min (stretch ≤ 45). If the regular
    (non-governance) suite alone floors at ~45–53 min (cf. #400/#405), the stretch may be unreachable without
    touching unrelated code — confirm the acceptance framing.

## 6. Limitations and unresolved risks

- Local hardware (Windows, ~104 ms/git spawn) cannot reproduce CI walls; all local numbers are ratios/spawn
  counts, explicitly not comparable to CI walls. The authoritative performance number is the single hosted
  exact-head run on the final PR head.
- The exec-bit negative (`test_extra_tracked_...`) cannot run on NTFS; pre-existing, identical on `main`.
- If the hosted run misses the goal, verdict is PERFORMANCE_NOT_ACCEPTED and no merge recommendation follows.
