# CI V4 FULL recovery — forensic report

Base: accepted `main` `957335405828091410c2c38638ad0cf3f3732fd2` (tree `48f3ded78c0d1e675b4a37c075890a140a8196e3`), the normal merge of PR #455 (accepted head `9e5a2f61b86c5dddb7b50fe30d682af909aaa996`).
Scope: CI only. No product, finance, UI, token, tax or Radar byte. No branch-protection, CODEOWNERS or required-check change. No `docs/ci_v5/epoch.json`. The V5 gate stays non-required.

**Verdict of this change: `FULL_RECOVERY_INCOMPLETE`.** It removes the dominant cause of the FULL timeout (measured, below), but it does **not** make FULL green: three tests fail on accepted `main`
for an independent, real reason that needs a Financial-Owner decision (section 4). Nothing here is, or may be read as, a green FULL witness. `FULL_PROVEN_GREEN` requires a hosted run on accepted `main`.

## 1. Evidence (hosted, observed — not speculation)

| Fact | Source |
|---|---|
| All 12 scheduled `CI V4 FULL` runs on `main` concluded `failure`, each after about 5.3 h (the supervisor budget is 19,200 s = 5.33 h). FULL has never been green. | runs `41991019709`, `42184838071`, `42351015813`, `42459282071`, `42584015081`, `42783123878`, `42982570864`, `43183116912`, `43391393290`, `43572279699`, `43692235471`, `43828509961` |
| Run `43828509961` (commit `c8b7e8133ec1`): `v3-regression / sequential / tests` failed with `FINCO_CI_SUPERVISOR TIMEOUT: budget 19200s exceeded`, exit 124, **2,242 of 25,406** tests recorded. | job `133167967701` |
| Recorded test time of those 2,242 tests: 18,956.8 s, of which `tests/test_ci_v3_outcome_reconciliation.py` **16,008.5 s** and `tests/fin_truth_b1/test_source_successor.py` **2,496.8 s** (97.6 % together). The other 2,160 recorded tests took about 451 s. | `CI_PROGRESS` lines |
| Per node: nine reconciliation nodes took 1,658–1,716 s each; `test_b1_source_complete_and_predecessor_history_unchanged` 623.8 s; seven `test_b1_undeclared_or_corrupt_layer_is_not_admitted[...]` 255–264 s each. | `CI_PROGRESS test` lines |
| The FULL job routes to `sequential` on every scheduled/dispatched run: `tools/ci_v3_production.route_mode` returns `parallel` only for `push`/`pull_request` events, FULL runs on `schedule`/`workflow_dispatch`. FULL is therefore always one unsharded pytest process. | `route_preflight`, job `133167905976` |
| `record` and `v3-regression / tests` fail only because the sequential job failed (fail-closed binding); `f01` (browser + 20 native cases) is green. | jobs `133328381831`, `133328432062`, `133167906287` |

## 2. Root cause (measured locally on the exact source)

Both slow modules ask the V4 exact-source cohort chain (C06 → B1 → B2 → B3 → V5 bootstrap → V5-2B → V5-3 → ..., 47 registered cohorts, including this successor) for the same immutable verdicts **outside** any
`fin_v2_cohorts.call_scope()`. Each nested call (`wf03.exact_blobs_ok` → `_wf06b_supersedes` → `u1._later_supersedes` → `on_bess01` → `onaccept01` → ...) then re-evaluates every downstream cohort
with its own `git` subprocesses: a profile of one `WF03.exact_blobs_ok(ref=HEAD)` showed **35,381 `git` processes in 150 s** and 14,292 repeated `bess02.signature_ok` calls, without finishing.
The composite governance gate, which does use `call_scope()`, evaluates the same chain in about 22 s.

| Measurement (same machine, same source) | Seconds |
|---|---|
| `tools.ci_v3_production.d029_source_facts()` on unmodified accepted `main`, one call | **3,511.9** |
| the same call inside one `call_scope()` | **25.1** (second call 20.8) |
| `tests/fin_truth_b1/test_source_successor.py`, this change, 9 passed | **26** wall (hosted baseline 2,496.8) |
| `tests/test_ci_v3_outcome_reconciliation.py`, this change, 66 passed + 3 failed (section 4) | **669** wall (hosted baseline: nine nodes alone 15,000+) |

Environment: 4-vCPU Linux sandbox, Python 3.13, Git; baseline run concurrently with other local work (it therefore over-states the baseline slightly). Reproduce:
`python3 -I time_facts.py <checkout>` calling `tools.ci_v3_production.d029_source_facts()` (baseline) versus the same call with the change.

## 3. The change (and what it is not)

Two test modules enter the **existing** `fin_v2_cohorts.call_scope()` once per test (a function-scoped autouse fixture). `call_scope()` memoises each cohort verdict for the duration of that one
block and drops it when the outermost block exits (its docstring: nothing is cached across calls, worktrees, refs, monkeypatches or mutations). Nothing else changes:

* no assertion, parameter, expected outcome, node, marker, skip, xfail or timeout changed; the node inventory is identical (one control test is *added*, see below);
* the negative tests patch the reader **before** their first call, so no verdict can predate a mutation (the tampered `main_web.py` / manifest / ledger variants still make `exact_blobs_ok()` and `valid()` return `False`; the positive test returns `True` on the same committed tree — they are not vacuous);
* `tests/test_ci_v3_outcome_reconciliation.py` additionally reads the immutable facts of the checked-out HEAD once per session (`_head_facts()`), every consumer receives its own deep copy, and the new control test
  `test_the_session_cached_head_facts_equal_freshly_read_facts` proves cached == freshly read and that a caller's mutation never reaches the cache;
* `tools/`, `.github/`, the V4 selector, scheduler, aggregator, weights, node split and required workflows are byte-identical to `main`.

Because every changed path must be owned by a registered V4 exact-source cohort, the change carries the finite, terminal successor `tests/ci_v4_full_recovery_scope.py`
(manifest `docs/ci_v5/full_recovery/SOURCE_SUCCESSOR.json`, own test `tests/test_ci_v4_full_recovery_scope.py`), registered once after `tests.ci_v5_gate_scope`, with one forward hook from the V5-3 module and
the literal tail extensions of the earlier layers and their tests. It owns exactly: this report, the two modules above, `docs/ci_v5/delta.json` (regenerated last) and the shared governance handoffs.

### File inventory

New: `tests/ci_v4_full_recovery_scope.py`, `tests/test_ci_v4_full_recovery_scope.py`, `docs/ci_v5/full_recovery/SOURCE_SUCCESSOR.json`, this report.
Replaced: `tests/test_ci_v3_outcome_reconciliation.py`, `tests/fin_truth_b1/test_source_successor.py`, `docs/ci_v5/delta.json`.
Shared governance handoffs (literal, pin-exact substitutions over accepted-main bytes): the composite registry and U1 discovery list (one more cohort), the V5-3 gate module (forward hook), the earlier layers' tail tuples
(C06, B1, B2, B3, V5 bootstrap, V5-2B) and the exact-tail tests that assert them, and the eight current-map manifests.

## 4. What is still red, and why this is not fixed here

Three tests in `tests/test_ci_v3_outcome_reconciliation.py` **fail on unmodified accepted `main`** (verified on a clean checkout of `957335405828`; run `43828509961` also shows an `F` right after the first of them):

* `test_the_authorized_transition_holds_on_the_real_reviewed_sources`
* `test_wf03_ci_state_rejects_mixed_blobs_and_missing_same_run_evidence`
* `test_the_real_head_is_exactly_the_ws2_state_and_the_receipt_binds_it`

First failing assertion: `d029_transition_problems(...)` returns `['Trust sources are not the exact reviewed blobs']`. The sub-check that fails is `WF03.accepts_ci_trust_state`, which requires the WS-2 manifest pins
(`docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json`) to equal the current blobs of the Trust sources. One pin has drifted: `tests/test_trust_readiness_registry.py` is pinned at `eeb8302dce…` but the file at `main`
is `cb8a6c1255…` since the BESS commits of 2026-11-09 (`cccdd557`, `3a20a297`), which re-pinned the file for their own cohort but not for the CI V3 D-029 trust-state chain.

This is a genuine governance-drift detection, not a timeout. Making it pass means re-authorising an exact Trust-source state of the D-029 reconciliation. That authority belongs to the Financial Owner; no agent
may invent or relax it, and this change deliberately does **not** edit `tools/ci_v3_production.py`, the D-029 constants or the WF03 state logic, nor weaken, skip or reclassify any of the three tests.

Unknown until a complete run: the other ~23,164 tests had not run when run `43828509961` timed out. Their duration and any genuine failures among them are **not** established by this change.
The remaining recorded time (about 451 s for ~2,160 tests) suggests the rest fits the budget, but that is an extrapolation, not a measurement.

## 5. Residual risks

* FULL stays on the sequential route (one process) by design here; sharding FULL would change `tools/ci_v3_production.py` trust logic and is intentionally not attempted.
* Any other test that evaluates the chain outside `call_scope()` is still slow; the profile above is how to find it (`CI_PROGRESS module` lines of a completed run).
* The memo is per test, not per session, so each of the ~60 reconciliation tests still pays about 10–25 s for the one fresh chain evaluation it needs.

## 6. Owner handoff — post-merge validation (not pre-authorised)

1. After the owner merges, run `CI V4 FULL` via `workflow_dispatch` on the new accepted `main` commit (or wait for the 01:23 UTC schedule). Record the run id, `head_sha`, every job conclusion and the
   `CI_PROGRESS` module table. Expect `tests/test_ci_v3_outcome_reconciliation.py` and `tests/fin_truth_b1/test_source_successor.py` to take minutes, not hours.
2. Expect the three failures of section 4 until the Financial Owner decides how the D-029/WS-2 Trust-source state is re-authorised (a separate, owner-approved, finite exact-source change). Do not accept a FULL
   that is green only because those tests were skipped, deselected, xfailed or relaxed.
3. Only after a genuine `success` of every FULL job and the `record` job at the exact accepted commit may a separate, isolated V5-2C promotion PR (`docs/ci_v5/epoch.json`, `PROMOTION_REQUIRES_OWNER`) be
   prepared. It needs its own V4 exact-source successor; V4 may block even that narrow PR (`PROMOTION_GOVERNANCE_BLOCKED`).
4. GitHub required-check settings, an independent approval identity or owner-held signing key, and the V5 gate activation remain separate owner decisions. Nothing here changes them.
