# SECURITY_EQUIVALENCE — bounded amortisation of repeated immutable proofs (Correction A)

Scope of the correction: `tests/wf06b_scope.py`, `tests/wf03_lifecycle_scope.py`,
`tests/fin_v2_wf06a_scope.py`, `tests/fin_v2_integration_409_scope.py`,
`tests/test_wf06b_scope.py` (additive negatives + the pinned historical missing-path set) and the WF-06B
manifest `docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json` (re-pins of exactly the reviewed files).
Nothing else changes. No financial, engine, workflow, deployment or frontend file is touched.

## 0. Correction A (this revision): the process-lifetime verdict cache was removed

The first revision of this PR shipped, in `wf06b_scope.py`, a process-lifetime verdict cache keyed by a
derived state key (`HEAD` + `git diff HEAD --binary` + untracked names/bytes + identity constants), claiming
the key covered "every mutable byte". **That claim was disproven** before this revision was pushed further,
by two reproducible counterexamples on ordinary git repositories (both reproduced on the pre-correction head
`dffe439`; commands and outputs in the correction commit and GPT6_REVIEW_PACKET.md):

| # | Configuration | Real change | `git diff HEAD --binary` sees it? | Pre-correction behaviour (state-keyed cache) | After Correction A |
|---|---------------|-------------|-----------------------------------|----------------------------------------------|--------------------|
| 1 | `core.filemode false` (POSIX) | `chmod +x` an owned file | **No** (mode hidden) | cached **True** returned — tamper masked | fresh evaluation stats the file: **False** |
| 2 | `update-index --assume-unchanged` | mutate a tracked owned file's bytes | **No** (byte change hidden) | cached **True** returned — tamper masked (reproduced: cached True, direct evaluation False) | fresh evaluation reads the real bytes: **False** |

A third identity weakness was also accepted: keying on `len(OWNED_PATHS)`/`len(SUPERSEDED)` cannot distinguish
a same-cardinality change of the guard's literal identity. Rather than attempt to prove an ever-growing state
key complete (and pay full-byte hashing on every per-pin hook invocation), **Correction A removes the
process-lifetime cache entirely**. `wf06b_scope.exact_blobs_ok` is now: one-outer-call scope memo (below), or
a full evaluation. The WF-06B layer therefore has no persistent state at all, and every evaluation outside one
outer call reads the real bytes, modes and git state directly.

The PR #409 seal's own `_state_key/_RESULTS` cache (`fin_v2_integration_409_scope.py`) predates this PR, is
unchanged by it, and is not relied on by this correction's security argument.

## 1. What changed, functionally

One memo layer, already established in this repository, now composes across the delegation chain:

**Call-scope memo (`scoped()`), shared by nested enters.** Unchanged contract: within ONE outer governance
call (single-threaded, no file written meanwhile) each cohort's `exact_blobs_ok(root, ref)` is computed once;
the memo is dropped at the outermost exit and never shared between separate outer calls. The behaviour change
is that a nested `scoped()` enter (the composite registry, or the older guards' outer calls entering the
downstream cohorts they delegate to) *shares* the outermost memo instead of pushing a fresh one, so one outer
operation computes each verdict at most once however deep the delegation cascades.

Additionally `wf03_lifecycle_scope.exact_blobs_ok/_valid` (and `scoped()`) enter the downstream cohorts'
one-call memos (`fin_v2_integration_409_scope`, `fin_v2_wf06a_scope`, `wf06b_scope`) for the duration of ONE
outer evaluation — exactly what `fin_v2_cohorts.valid()` (the composite registry) already did for composite
calls. WF-03 and WF-06A deliberately keep **no** state cache of their own: their negatives monkeypatch their
`_read`/`_git`, and a per-call-scope memo never outlives the call in which a monkeypatch is active.

**Fail-closed rule for the memo:** a failed or ambiguous evaluation is never turned into permission to reuse
anything — the memo stores verdicts only for the exact `(root, ref)` pair computed inside one call, and any
exception inside an evaluation propagates as False exactly as before (the `except` clauses are unchanged).

## 2. Why one-outer-call memoisation is safe, and what can and cannot be cached

The trust boundary is the one documented by the existing `scoped()` contract (and relied on by the composite
registry since its introduction): **within one outer governance call the process is single-threaded and no
file is written**, so the immutable inputs (git objects, manifest bytes, source bytes, modes, git config) are
fixed for the memo's whole lifetime. The memo dies with the call; the next outer call re-reads everything.

| Input class | Cached? | Reason |
|---|---|---|
| Immutable git objects (commit/tree/blob ids) | Yes (pre-existing `lru_cache`s) | Immutable by git's object model |
| Working-tree / staged / index bytes, mode/type/symlink state, untracked files, git config, `assume-unchanged` flags | **Not cached at any layer of this correction** | Every evaluation outside a scope reads them directly; inside a scope they cannot change (single-threaded, no writes) |
| Monkeypatched readers (`_read`/`_git`) of WF-03 / WF-06A | Never cached — those layers keep call-scope memoisation only | The memo lifetime is one call; a patch active in that call is consistently observed by it |
| Verdicts across processes | No | pytest-xdist workers are separate processes |
| Time-based expiry | Not used and not needed | No persistent cache exists to expire |

The per-path tamper negatives keep running their real mutations in disposable git worktrees exactly as before.
Their runtime is unchanged: negatives do not amortise (each mutation is a fresh evaluation); positives
(repeated identical-state asks inside one outer call) amortise to one evaluation.

## 3. Governance successor procedure followed

`tests/wf03_lifecycle_scope.py`, `tests/fin_v2_wf06a_scope.py`, `tests/fin_v2_integration_409_scope.py`,
`tests/wf06b_scope.py` and `tests/test_wf06b_scope.py` are exact-source-pinned files. The correction updates
only their blobs in the WF-06B manifest (`docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json`,
`source_blobs`), preserving:

- every older cohort's manifest byte-identically (the supersession hooks accept the moved files exactly as
  designed: "older cohort accepts a different current blob only through `supersedes(path, blob)`, true only
  while THIS cohort is exact and pins exactly that blob");
- `base`, `base_tree`, `base_blobs`, schema, and the literal path set — the only additions are the four
  incident documents, each a finite literal path in `wf06b_scope.TEST_AND_DOC_PATHS` (no wildcards);
- the CI V3 collection identity: the historical parametrized node set of
  `test_missing_owned_path_fails_closed` is pinned literally (it is exactly the first six sorted owned paths
  of the #410 authenticated baseline collection), so no original node is removed or renamed; the four new
  documents get separately named deletion negatives;
- the WF-03 pin set, historical maps, B1 layer, predecessor ledgers, #409 seal ledger and closed-world
  changed-path checks (all re-verified by the suites below).

## 4. Correctness evidence (local, this machine; hosted exact-head run follows)

- Collection identity: `pytest --collect-only` over the full suite, base (`3e00acab`) vs corrected head —
  **zero removed original node IDs** (full-suite and `tests/test_wf06b_scope.py` diffs both recorded); the
  only differences are the additive Correction-A negatives.
- `tests/test_wf06b_scope.py`: all baseline nodes pass, plus the new negatives (mutation → restore → different
  mutation; staged tamper; untracked evidence vs untracked source; patched identity constant; same-cardinality
  `OWNED_PATHS`/`SUPERSEDED` swaps; per-root separation; `assume-unchanged` counterexample; POSIX
  mode-change counterexample; call-scope drop semantics; shared-scope amortisation). The two pre-existing
  Windows-only exec-bit negatives are precisely identified below.
- Full governance battery (`test_wf06b_scope`, `test_wf03_lifecycle_scope`, `test_fin_v2_integration_409_scope`,
  `test_fin_v2_wf06a_scope`, `test_ci_v3_outcome_reconciliation`): outcome parity vs base recorded in
  TIMING_LEDGER.md.

## 5. Known limitations (precise, not silently green)

- `test_extra_tracked_extra_untracked_and_executable_paths_fail_closed` (pre-existing, PR #410) cannot
  exercise the exec-bit negative on Windows/NTFS (a chmod cannot represent the POSIX executable bit); it
  fails identically on unmodified `main` locally and passes on the Linux CI runners. Unchanged by this PR.
- `test_executable_mode_change_hidden_from_git_diff_is_rejected` (new, Correction A counterexample 1) has the
  same NTFS limitation locally; on Windows it takes an explicit `pytest.skip('POSIX-only: ...')` — visible as
  SKIPPED, never silently green — and runs fully on the POSIX CI runners.
- Local measurement hardware is ~45× slower per git spawn than the CI runners; only spawn counts, verdicts and
  ratios transfer. The authoritative performance evidence is the hosted eight-worker CI V3 run on the exact
  final PR head.
- The unsupported-inputs list is explicit: with the persistent cache removed there is no cached-True path left
  to falsify; the residual trust assumptions are (a) single-threaded, no-write outer calls for the scope memo,
  and (b) git object immutability for the pre-existing immutable-object caches.
