# GPT6_REVIEW_PACKET — CI V3 governance amortisation correction (Draft PR #414, DO NOT MERGE)

Independent reviewer: GPT-6 High. This packet links every claim to a checkable artifact; nothing is
cherry-picked — the failing/negative rows are included wherever they exist. Revision: **Correction A**
(supersedes the first revision's design; see §2 — the persistent verdict cache was removed after its safety
claim was disproven).

## 1. What to review

- PR: https://github.com/Finco-Protocol/FincoProtocol/pull/414
- Branch: `perf/ci-v3-governance-amortization-post410` (from `main` @ `3e00acab71ea4c2bd9e7396e5bee609225212623`)
- First-revision head: `dffe439dcffd0588f2b9c2a7e67db0957cbd34e1` (failed run 41543769701, plan phase — see §3)
- Correction-A head: <filled at push — exact SHA/tree>
- Diff (5 files + 4 new documents):
  - `tests/wf06b_scope.py` — shared `scoped()` (nested enters share the outermost one-outer-call memo). **No
    persistent verdict cache** (Correction A removed the first revision's `_state_key/_RESULTS`).
  - `tests/wf03_lifecycle_scope.py` — `_downstream_scopes()` entered by `exact_blobs_ok`/`valid`/`scoped()`
    (composite-registry behaviour for standalone calls); **no** state cache at this layer.
  - `tests/fin_v2_wf06a_scope.py` — shared `scoped()` only (no state cache: its negatives monkeypatch its `_read`).
  - `tests/fin_v2_integration_409_scope.py` — shared `scoped()` only.
  - `tests/test_wf06b_scope.py` — the historical `test_missing_owned_path_fails_closed` set pinned literally
    (exactly the six nodes of the #410 authenticated baseline collection; no sorting/slicing dependence),
    separately named deletion negatives for the four new incident documents, and the Correction-A negatives
    (§4). No original node renamed, removed, xfailed, skipped or weakened.
  - `docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json` — re-pins of exactly the reviewed files + the
    four document pins.
  - `docs/ci_v3/incidents/ci_v3_governance_amortization/` — ROOT_CAUSE / TIMING_LEDGER /
    SECURITY_EQUIVALENCE / this packet.

## 2. Correction A: why the persistent cache is gone (falsified, not re-designed)

The first revision claimed its state key ("HEAD + `git diff HEAD --binary` + untracked bytes + identity
constants") covered every mutable input. Two counterexamples on ordinary git repositories disprove that class
of claim; both were reproduced against head `dffe439` before this correction:

- **Counterexample 1 (POSIX mode hiding).** `git config core.filemode false`, then `chmod +x` an owned file:
  `git diff HEAD --binary` stays empty while the file really became executable. The exact check rejects
  executable owned files, but a cached True was returned. (POSIX-only; NTFS cannot represent the bit.)
- **Counterexample 2 (byte hiding).** `git update-index --assume-unchanged tests/wf06b_scope.py`, then mutate
  the tracked file: `git diff HEAD --binary` empty, state key unchanged, cached True returned — reproduced
  verbatim on `dffe439`: warm verdict True → tamper → `exact_blobs_ok(wt)` **True (masked)**; the same state
  evaluated with the cache cleared returned **False**. Transcript (repro_blocker_b.py, disposable worktree):
  1. warm verdict on pristine worktree: True; cached entries after warm: 1
  2. `git diff HEAD --binary` length after tamper: 0 (empty = invisible to the state key)
  3. state key still the warm one: True → cached verdict: True
  4. `exact_blobs_ok(wt)` with cache active: **True** (tamper MASKED)
  5. same state, uncached direct evaluation: **False** (the direct check DOES see the tamper)
- **Identity weakness.** The key carried `len(OWNED_PATHS)`/`len(SUPERSEDED)`; a same-cardinality swap of the
  guard's literal identity could reuse an inappropriate cached True.

A derived state key cannot prove completeness over git's hiding modes without reimplementing git's
index/worktree semantics. The chosen fix removes the persistent cache: `wf06b_scope.exact_blobs_ok` is now
one-outer-call scope memo or a full evaluation. Measured cost of that choice (same machine/tree): WF-03 outer
call 26.1 s / 124 spawns cold, 4.4 s / 23 warm (vs 896 s / 8,617 before) — the speed-up survives without any
persistent cache; older cohorts' standalone hooks pay full evaluations again (WF-06A standalone 78.8 s / 391
spawns), which is the accepted security-first trade.

## 3. Exact links

- Regression runs: #405 run 41174457140 (wf03: worker-5, 174 cases / 12 s),
  #409 run 41249085437 (wf03: worker-1, 185 / 4,979 s), #410 run 41372476713 (wf03: worker-0, 185 / 10,145 s —
  100 % of worker-0's testcase time), #413 run 41495823762 (product stream, worker-0 = 181 min; untouched here).
- First hosted run of this PR: 41543769701 — FAILED at `safety-and-smoke / plan` (job 125614860267):
  `ContractError: original nodes removed; reviewed reconciliation authority required:
  ['tests/test_wf06b_scope.py::test_missing_owned_path_fails_closed[docs/react_migration/wf06b_a_plus/GOVERNANCE_SUCCESSOR_PLAN.md]']`.
  The CI V3 collection contract did exactly its job: adding four document paths to `wf06b_scope.OWNED_PATHS`
  shifted the `sorted(...)[:6]` slice of the missing-path negative and removed one original baseline node from
  collection. Correction A pins that historical node set literally (verified: full-suite `--collect-only`
  diff base vs head = **zero removed IDs**); that run produced no throughput evidence and no conclusion about
  the fix's speed is drawn from it.
- Correction hosted run: <filled after the single exact-head run of this revision>.
- Diff of the onset commits: `git diff ebf1f151 b7bfc4ed -- tests/wf03_lifecycle_scope.py` (adds `_wf06a_repin`,
  `_int409_admits`, `_b1_layer_ok`, historical-map delegation) and `git diff b7bfc4ed 3e00acab` (adds the
  `_wf06b_supersedes`/`_wf06b_allows` hooks to WF-03, the #409 seal, WF-06A and eight older cohorts).
- Precedent for the one-outer-call memo: `fin_v2_cohorts.valid()` (composite registry) and each cohort's
  `scoped()`; the *persistent*-cache precedent (`cddd5e0c`) is explicitly NOT relied on by this correction.

## 4. Test commands actually run

```bash
python -m pytest tests/test_wf06b_scope.py tests/test_wf03_lifecycle_scope.py \
  tests/test_fin_v2_integration_409_scope.py tests/test_fin_v2_wf06a_scope.py \
  tests/test_ci_v3_outcome_reconciliation.py -q -rf        # correction tree
git worktree add --detach <wt> 3e00acab && <same command>  # baseline tree, outcome parity
python -m pytest tests/ --collect-only -q                  # node inventory, base vs head
python -I profile_wf03.py <checkout>                        # single-call spawn/time profile
python -I repro_blocker_b.py <checkout>                     # counterexample 2 transcript (pre-correction head)
```
(Local-only plugin suppression `-p no:pytest_ethereum` was needed on this Windows machine because the global
site-packages ship a broken `web3` pytest plugin; CI environments are unaffected.)

## 5. Security-equivalence claims to challenge (falsification guide)

1. With the persistent cache removed, every `exact_blobs_ok` evaluation outside one outer call reads real
   bytes, modes, index state and git config. *Challenge: find any remaining cached-True path that survives a
   real mutation.* The only memo is the one-outer-call scope memo.
2. The scope memo's trust boundary: single-threaded outer call, no file written meanwhile (the pre-existing
   documented `scoped()` contract, relied on by the composite registry). *Challenge: name a caller that writes
   files inside one outer governance call.*
3. Collection identity: zero removed original node IDs (full-suite collect diff); historical negatives run
   exactly as written; additions are genuinely additional.
4. No protected surface (`financial_engine/`, `finco_core/`, `domain/`, `.github/`, `tools/`, `main_web.py`,
   frontend, static) is modified; the only manifest changes are the re-pinned governance files and the four
   document pins in the WF-06B seal.
5. The governance successor procedure is followed exactly as #410 did (literal pins; older manifests untouched;
   supersession hooks accept the moved governance files).

## 6. Questions the independent reviewer should press

1. **Scope-memo boundary**: is the single-threaded/no-write outer-call contract acceptable for every current
   caller of the per-path hooks (WF-03, WF-06A, INT, the eight older cohorts, the composite registry)?
2. **Residual cost**: without the persistent cache, the older cohorts' standalone per-pin hooks re-run full
   WF-06B evaluations. Is that acceptable, or should a *provable* cache design (e.g. evaluating the real
   `stat()`/bytes of every owned path into the key) be pursued later with its own negatives?
3. **Collection identity**: the historical missing-path set is now pinned literally. Any objection to pinning
   versus deriving, given the CI contract rejects removals anyway?
4. **The [:6] incident**: the first hosted run failed on a node-identity removal. What other parametrizations
   in the suite derive from mutable module constants (`sorted(...)`/slices) and could silently shift again?
5. **WF-03 layer has no state cache** (deliberate: its negatives monkeypatch `F._read`/`F._git`). Remaining
   per-outer-call cost is 23–124 spawns. Acceptable?
6. **Manifest re-pin authority**: the correction re-pins five governance files and adds four document pins in
   the WF-06B manifest under the task authorization (bounded CI performance correction). Within WF06B-D3's
   letter, or does it need a fresh Owner decision line in the `authorization` field?
7. **Counterexample 1 coverage**: the POSIX mode-change negative takes an explicit SKIPPED on NTFS hosts.
   Sufficient, or should a Windows-representable analogue (e.g. `update-index --chmod=+x` staged-mode path) be
   added?
8. **Untracked-evidence cost**: no hashing is performed anymore (no state key); the untracked check is a plain
   `ls-files --others` admission test per evaluation. Confirm no residual cost concern.
9. **Performance acceptance**: the hosted gate is slowest-worker ≤ 60 min (stretch ≤ 45). If the regular
   (non-governance) suite alone floors at ~45–53 min (cf. #400/#405), the stretch may be unreachable without
   touching unrelated code — confirm the acceptance framing.
10. **INT seal's pre-existing `_RESULTS`**: this PR neither introduced nor modified it. Should its state-key
    completeness be independently re-audited in a separate governance stream?

## 7. Limitations and unresolved risks

- Local hardware (Windows, ~104 ms/git spawn) cannot reproduce CI walls; all local numbers are ratios/spawn
  counts, explicitly not comparable to CI walls. The authoritative performance number is the single hosted
  exact-head run on the final PR head.
- The two exec-bit negatives cannot exercise on NTFS (one pre-existing, one new with explicit SKIPPED);
  both run fully on the Linux CI runners.
- If the hosted run misses the goal, verdict is PERFORMANCE_NOT_ACCEPTED and no merge recommendation follows.
