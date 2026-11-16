# CI V4 FULL recovery — forensic report

Base: accepted `main` `957335405828091410c2c38638ad0cf3f3732fd2` (tree `48f3ded78c0d1e675b4a37c075890a140a8196e3`), the normal merge of PR #455 (accepted head `9e5a2f61b86c5dddb7b50fe30d682af909aaa996`).
Scope: CI only. No product, finance, UI, token, tax or Radar byte. No branch-protection, CODEOWNERS or required-check change. No `docs/ci_v5/epoch.json`. The V5 gate stays non-required.

**Verdict of this change: `FULL_RECOVERY_INCOMPLETE`** (plus `TRUST_HISTORY_OWNER_DECISION_REQUIRED` and `SCHEDULER_FOLLOWUP_REQUIRED`, section 7). It removes the dominant cause of the FULL timeout (measured, below), but it does **not** make FULL green: three tests fail on accepted `main`
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

## 7. PR runtime (Correction B) — what the hosted CI V4 PR run really spends

Observed run: `CI V4 PR` `43946034993` at PR head `8b2ad543afe524813b6929e62be23aa102f433a5` (all six V4 checks `success`, wall time 20:05 → 22:26 UTC, about **2 h 21 min**). Plan artifact `14263548564`: RISK, 3 workers, `module_plan`
(no selected module is on the trusted node-split allowlist), 53 selected modules, **predicted critical path 1,244.3 s (20.7 min)**, 20 selected modules without a weight. JUnit: `shard-0` artifact `14273596713`, `shard-1` `14268000950`, `shard-2` `14277023842`.

| Shard | Modules | Predicted (sum of known weights, s) | Unweighted modules | Actual pytest (JUnit sum, s) | Tests |
|---|---|---|---|---|---|
| shard-0 | 17 | 854 | 7 | **4,953** (82.6 min) | 914 |
| shard-1 | 19 | 884 | 6 | 1,556 (26.0 min) | 854 |
| shard-2 | 17 | 854 | 7 | **8,398** (140.0 min, critical path) | 987 |

The estimate error is almost entirely three governance test modules whose weights in `docs/ci_v4/module_weights.json` are stale samples of a much shorter exact-source chain:

| Module (own test of an old cohort) | Predicted s | Actual s | Ratio | Tests | Shard |
|---|---|---|---|---|---|
| `tests/test_wf03_lifecycle_scope.py` | 176.0 | 4,809.1 | 27× | 185 | 2 |
| `tests/test_trust_readiness_registry.py` | 69.6 | 4,278.7 | 61× | 159 | 0 |
| `tests/test_u1_scope.py` | 259.0 | 2,315.8 | 8.9× | 100 | 2 |

These three alone are 11,403.6 s. The four dominant Trust testcases are `test_d029_trust_successor_exact_baseline_and_exact_new_content` 1,642.7 s, `test_demo_retention_exception_accepts_only_exact_approved_content` 821.0 s,
`test_f4_csrf_correction_preserves_historical_content_and_authorities` 814.3 s and `test_csrf_registry_correction_is_only_the_two_approved_sentences` 803.7 s (= 4,081.7 s, 95 % of the module). The 20 unweighted modules measured 2,554 s in total
(largest: `test_ci_v4_lean_tamper_matrix.py` 589.2 s, `test_ci_v4_perf_scope.py` 326.7 s, `test_ci_v5_bootstrap_scope.py` 140.8 s). `test_ci_v3_outcome_reconciliation.py` (this change) measured 426.0 s hosted for 70 nodes (predicted 187.5 s).

### 7.1 Cause and measured effect (same checkout, same machine)

`WF03.matches` → `valid` evaluates the exact-source cohort chain outside any `fin_v2_cohorts.call_scope()`. One `WF03.matches("app/trust_readiness/registry.py", <current bytes>)` call:

| Variant | Seconds | `git` child processes | Verdict |
|---|---|---|---|
| unscoped, accepted `main` `957335405828` (46 cohorts) | **757.4** | **33,019** | `True` |
| inside one `call_scope()` | **14.4** | **1,591** | `True` |

Out-of-tree proof of the proposed per-test fixture (a pytest plugin with the same autouse fixture, repository untouched): `tests/test_trust_readiness_registry.py` collects **159** and **159 passed** in **105 s** run alone
(180 s while three other jobs ran), against **4,278.7 s** hosted. The remaining local-environment failures seen without dependencies (`No module named 'fastapi'`) are environment, not assertions: they pass after `pip install -r requirements.txt`.

### 7.2 Why the Trust test (and `test_wf03_lifecycle_scope.py`, `test_u1_scope.py`) is NOT changed here — `TRUST_HISTORY_OWNER_DECISION_REQUIRED`

All three files are pinned by the earliest exact-source cohorts (the Trust test also by the D-029/WS-2 provenance and the closed BESS cohort). A one-fixture performance edit of any of them, owned by this cohort's manifest, makes the central governance gate fail with
**44 of 47 cohorts not exact** (verified for the Trust test and, separately, for the two cohort-own tests; every experiment reverted, the tree is byte-identical to `main` for all three). The older cohorts accept a changed pin only through
bespoke hooks; extending those hooks is a change to Trust/WS-2/D-029 history that needs the Financial Owner and the cohort owners, not an agent. Nothing here claims such an approval.

**Finite, auditable proposal (not applied).** Before: blob `cb8a6c12551600f55b6a9c8c75b1cef2f5f1c519`, sha256 `33fc0a33ecb598ea609a4d23ff090c4c1c0051940d6aa505bc6d1a0f33d72bdd`. After: blob `311c49f80ff8b6cb8f3756aa3145b92a9d5c30d5`, sha256 `04b1e9922ed49ca4e27febd0cafffe719ffdcd2a2c68a0d91ad180314b65c878`.
One autouse fixture entering the existing `call_scope()` per test (memo asserted empty on entry and gone afterwards; nothing cached across tests/refs/mutations) and one negative control test (a modified protected source is still rejected inside one scope and the positive verdict is not poisoned).
(In the diff below `(at)` stands for the at-sign, which the repository's public-safety scanner reads as an e-mail marker.) The same fixture is the proposal for the two cohort-own tests. Expected effect: module 4,278.7 s → ~105 s; `test_wf03_lifecycle_scope.py` and `test_u1_scope.py` analogous (not measured).

```diff
diff --git a/tests/test_trust_readiness_registry.py b/tests/test_trust_readiness_registry.py
index cb8a6c12..311c49f8 100644
--- a/tests/test_trust_readiness_registry.py
+++ b/tests/test_trust_readiness_registry.py
(at)(at) -8,6 +8,7 (at)(at) from pathlib import Path
 import pytest
 
 from app.trust_readiness import registry as R
+from tests import fin_v2_cohorts as COHORTS
 from app.trust_readiness.contracts import EvidenceKind, ReadinessStatus as S
 
 ROOT = Path(__file__).resolve().parent.parent
(at)(at) -15,6 +16,22 (at)(at) IMPLEMENTATION = {EvidenceKind.CODE, EvidenceKind.CI}
 VERIFICATION = {EvidenceKind.TEST, EvidenceKind.CI}
 
 
+_SCOPE_MEMOS = []
+
+
+(at)pytest.fixture(autouse=True)
+def one_governance_call_per_test():
+    """Each test is ONE outer exact-source governance call: every cohort verdict the historical-registry checks ask for (WF03 ``matches`` / ``valid``, the chain behind them) is computed once per
+    test instead of once per nested call, and dropped when the test ends. The memo starts EMPTY for every test and is gone afterwards: nothing is cached across tests, refs, mutations or
+    monkeypatches, and no assertion, parameter or expected value of this module changes."""
+    with COHORTS.call_scope():
+        memo = COHORTS._CALL[-1]
+        assert memo == {}, "a governance verdict leaked into this test from another one"
+        _SCOPE_MEMOS.append(memo)
+        yield
+    assert not COHORTS._CALL, "the governance scope outlived its test"
+
+
 def _everything():
     return list(R.all_items()) + list(R.DATA_STORES) + list(R.KNOWN_GAPS)
 
(at)(at) -1958,3 +1975,16 (at)(at) def test_d029_successor_refuses_a_second_application_or_a_missing_anchor():
         _d029_registry(_d029_registry(base))
     with pytest.raises(ValueError):
         _d029_registry(base.replace(D029_RUN_INTENTS_ANCHOR, "", 1))
+
+
+def test_the_governance_scope_is_fresh_per_test_and_never_confers_a_stale_pass():
+    """Negative control for the per-test governance scope: a modified protected source is still rejected inside one scope, in any order, and a positive verdict is never poisoned."""
+    from tests import wf03_lifecycle_scope as WF03
+    assert COHORTS._CALL and not any(m is COHORTS._CALL[-1] for m in _SCOPE_MEMOS[:-1])      # a fresh memo object, not one an earlier test used
+    path = "app/trust_readiness/registry.py"
+    current = _read_current(path).strip()
+    assert WF03.matches(path, current + "\n")                                                  # the real pinned bytes with a valid chain
+    assert not WF03.matches(path, current + "\nFINCO is certified.\n")                         # one appended claim
+    assert not WF03.matches(path, current[:-1] + "\n")                                         # one byte fewer
+    assert WF03.matches(path, current + "\n")                                                  # and back: the positive verdict was not poisoned by the rejections
+
```

### 7.3 Earlier D-029 state-C hook, reverted

An intermediate commit of this PR (`8b2ad543`) let the D-029 CI trust state accept a Trust pin that a later reviewed cohort of the chain had pinned, which made the three reconciliation tests pass. That is a re-authorisation of an exact Trust-source state and
therefore a Financial-Owner decision; it is **reverted** (`tests/wf03_lifecycle_scope.py` is byte-identical to `main` again), the three tests fail as on `main` (section 4), and nothing is hidden. If the Financial Owner decides to authorise that state, the change is one reviewed commit.

### 7.4 Scheduler — `SCHEDULER_FOLLOWUP_REQUIRED` (protected V4 files, not changed here)

Weights, scheduler and node-split policy are frozen control files; a PR-head policy is never authoritative. Evidence-based proposal for a separately owner-reviewed, exact-source-successor change:
(1) re-measure and replace the three stale weights above and add measured weights for the 20 unweighted modules (table above and the matrix in the PR comment); (2) after (1) the scheduler would isolate the three modules (critical path then ≈ 4,300–4,800 s each, i.e. no better than today) — so the real remedy is the scoped
fixture of 7.2, after which the weights drop to about 100 s each; (3) node-splitting the Trust module (four testcases = 95 % of it) would cut its critical path to 1,642.7 s but needs the module on the trusted allowlist and a fixture/provenance isolation proof; not attempted. No timeout was raised, no worker count changed.

### 7.5 V5 gate

`V5 gate (trusted base)` is non-required and fails closed by design: `AUTHORIZATION_BLOCKED` (`POLICY.APPROVERS=()`), `TRUST_NOT_ESTABLISHED` (no trusted `docs/ci_v5/epoch.json`), `FULL_WITNESS_NOT_VERIFIED`, and `INTEGRITY_FAIL: DELTA_RESULT_MISMATCH, UNDECLARED_ADD` because the new V4-bound manifest
`docs/ci_v5/full_recovery/SOURCE_SUCCESSOR.json` is not in the trusted-base `POLICY.V4_BOUND_EXEMPT` (a PR cannot exempt its own manifest; a separately reviewed trusted-base policy change is needed). It does not contribute to the PR wall time and is not bypassed.
