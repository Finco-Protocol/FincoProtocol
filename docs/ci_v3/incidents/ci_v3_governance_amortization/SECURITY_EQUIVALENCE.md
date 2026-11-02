# SECURITY_EQUIVALENCE — bounded amortisation of repeated immutable proofs

Scope of the correction: `tests/wf06b_scope.py`, `tests/wf03_lifecycle_scope.py`,
`tests/fin_v2_wf06a_scope.py`, `tests/fin_v2_integration_409_scope.py`,
`tests/test_wf06b_scope.py` (additive negatives only) and the WF-06B manifest
`docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json` (re-pins of exactly the five reviewed files).
Nothing else changes. No financial, engine, workflow, deployment or frontend file is touched.

## 1. What changed, functionally

Three memo layers now compose, all already established in this repository:

1. **Call-scope memo (`scoped()`), now shared by nested enters.** Unchanged contract: within ONE outer
   governance call (single-threaded, no file written meanwhile) each cohort's `exact_blobs_ok(root, ref)` is
   computed once; the memo is dropped at the outermost exit and never shared between separate outer calls.
   The only behaviour change: a nested `scoped()` enter (the composite registry, or the older guards' outer
   calls entering the downstream cohorts they delegate to) *shares* the outermost memo instead of pushing a
   fresh one, so one outer operation computes each verdict at most once however deep the delegation cascades.
2. **WF-03 outer scope entry.** `wf03_lifecycle_scope.exact_blobs_ok/_valid` (and `scoped()`) now enter the
   downstream cohorts' one-call memos (`fin_v2_integration_409_scope`, `fin_v2_wf06a_scope`, `wf06b_scope`)
   for the duration of ONE outer evaluation — exactly what `fin_v2_cohorts.valid()` (the composite registry)
   already did for composite calls. Standalone WF-03 calls behave like composite calls.
3. **WF-06B full-state verdict cache.** `wf06b_scope.exact_blobs_ok` gains the *verbatim construction* the
   PR #409 seal has shipped since commit `cddd5e0c` ("make the seal cheap and safely memoised"): a
   process-lifetime `_RESULTS` (bounded, cleared past 64 entries) keyed by `_state_key`.

## 2. Why the WF-06B state cache is fail-closed

`_state_key(root, ref)` is (`wf06b_scope.py`):

- for an explicit ref: the resolved immutable commit SHA, plus this module's governance identity constants;
- for the working tree: `HEAD` + `hash(git diff HEAD --no-ext-diff --binary)` (every tracked byte difference,
  staged or not, **including deletions and mode changes**) + `hash(sorted(untracked names + full bytes))`,
  plus the identity constants `BASE`, `BASE_TREE`, `SCHEMA`, `MANIFEST`, `len(OWNED_PATHS)`, `len(SUPERSEDED)`
  **read at call time**.

Consequences:

- **Any** flipped byte anywhere in tracked or untracked files changes the key → the cached verdict is never
  reused for different bytes → the exact check re-runs and fails closed.
- A forged *constant* (the one monkeypatch-style negative this cohort has, `monkeypatch.setattr(W, 'BASE_TREE', ...)`)
  changes the key → fresh full evaluation with the forged constant → still fails closed.
- A cached True is only ever returned for byte-identical states (e.g. a test that restores exactly what it
  mutated — which the pre-existing PR-#409-seal design already reuses deliberately).
- Restored-then-different-mutation sequences get fresh keys both times; the second mutation is caught after
  two warm verdicts (covered by new negatives).
- The cache is per-`str(root)` and per-ref: a mutated disposable worktree never inherits a verdict computed
  for the real tree and vice versa (multi-repo / temp-root separation negative added).
- Nothing is keyed by PR number, branch name, environment variable or HEAD alone.

## 3. What can and cannot be cached

| Input class | Cached? | Reason |
|---|---|---|
| Immutable git objects (commit/tree/blob ids, `BASE:path` values) | Yes (already, pre-existing `lru_cache` and this cache's key) | Immutable by git's object model |
| Working-tree / staged / index bytes of tracked files | Only as part of the full-state key | The key digest covers them; a change always re-validates |
| Untracked files (incl. `evidence/`) | Only as part of the full-state key (names + bytes) | Same |
| File mode / type / symlink state of owned paths | Covered by `git diff HEAD --binary` in the key; checked fresh on every miss | Mode change ⇒ new key |
| Monkeypatched readers (`_read`) of WF-03 / WF-06A | **Never cached at those layers** — WF-03 and WF-06A deliberately gained **no** state cache, so their monkeypatch-reader negatives run the real patched reader every time | A bulk state key cannot observe a patched per-path reader; those cohorts keep per-call-scope memoisation only |
| Monkeypatched `W.BASE_TREE` (WF-06B) | Cached only per distinct constant tuple | Constants are in the key |
| Verdicts across processes | No | pytest-xdist workers are separate processes; nothing is shared |

The per-path tamper negatives keep running their real mutations in disposable git worktrees exactly as before;
every one of them produces a new state key and a fresh full validation. Their runtime is intentionally
unchanged (negatives do not amortise; positives do).

## 4. Governance successor procedure followed

`tests/wf03_lifecycle_scope.py`, `tests/fin_v2_wf06a_scope.py`, `tests/fin_v2_integration_409_scope.py`,
`tests/wf06b_scope.py` and `tests/test_wf06b_scope.py` are exact-source-pinned files. The correction updates
only their blobs in the WF-06B manifest (`docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json`,
`source_blobs`), preserving:

- every older cohort's manifest byte-identically (the supersession hooks accept the five moved files exactly
  as designed: "older cohort accepts a different current blob only through `supersedes(path, blob)`, true only
  while THIS cohort is exact and pins exactly that blob");
- `base`, `base_tree`, `base_blobs`, schema, the literal path set (no path added or removed; the four incident
  documents listed in section 6 are the only additions, each a literal reviewed path);
- the WF-03 pin set, historical maps, B1 layer, predecessor ledgers, #409 seal ledger and closed-world
  changed-path checks (all re-verified by the suites below).

## 5. Correctness evidence (local, this machine; hosted exact-head run to follow)

- `tests/test_wf06b_scope.py`: 96/97 pass on Windows. The single failure
  (`test_extra_tracked_extra_untracked_and_executable_paths_fail_closed`) is a **pre-existing Windows
  limitation** (NTFS `chmod` cannot produce POSIX exec bits, so the owned-file-made-executable negative cannot
  be reproduced locally); it fails identically on unmodified `main` in a detached worktree and passes on the
  Linux CI runner fleet. Node inventory otherwise identical to `main`.
- Full governance battery (`test_wf06b_scope`, `test_wf03_lifecycle_scope`, `test_fin_v2_integration_409_scope`,
  `test_fin_v2_wf06a_scope`, `test_ci_v3_outcome_reconciliation`) and the older-cohort suites: outcome parity
  vs `main` recorded in TIMING_LEDGER.md (same node ids, same outcomes, plus the six additive negatives).
- Same-process cache-invalidation negatives added: mutation after a successful check; restoration followed by a
  different mutation; staged-index tamper; untracked-evidence vs untracked-source distinction; forged identity
  constant after a warm verdict; per-root separation; shared-scope amortisation with restores.

## 6. New files in this correction

- `docs/react_migration/wf06b_a_plus/CI_V3_GOVERNANCE_AMORTIZATION_ROOT_CAUSE.md`
- `docs/react_migration/wf06b_a_plus/CI_V3_GOVERNANCE_AMORTIZATION_TIMING_LEDGER.md`
- `docs/react_migration/wf06b_a_plus/CI_V3_GOVERNANCE_AMORTIZATION_SECURITY_EQUIVALENCE.md`
- `docs/react_migration/wf06b_a_plus/GPT6_REVIEW_PACKET.md`

Each is a finite literal path added to `wf06b_scope.TEST_AND_DOC_PATHS` and pinned in the manifest. No
wildcards. (The same pattern as PR #410's own `P00.md` / `GOVERNANCE_SUCCESSOR_PLAN.md`.)

## 7. Known limitations

- The Windows-local measurement environment is ~45× slower per git spawn than the CI runners (104 ms vs
  ≈2.4 ms measured); absolute local walls are therefore not comparable to CI walls — only spawn counts,
  verdicts and ratios are. The authoritative performance evidence is the hosted eight-worker CI V3 run on
  the exact final PR head.
- `test_extra_tracked_extra_untracked_and_executable_paths_fail_closed` cannot exercise the exec-bit negative
  on Windows (pre-existing; unchanged by this PR).
- The untracked-hash component of the state key reads every untracked file's bytes on each cache-miss state
  key computation. This is the PR #409 seal's reviewed construction, unchanged; on CI the untracked set is
  small (gitignored build artefacts are excluded).
