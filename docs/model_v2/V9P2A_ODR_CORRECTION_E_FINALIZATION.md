# V9-P2a / OD-R — Correction E: Final Financial Evidence Contract

**Status: UNAPPROVED financial candidate (local).** Changed protected blobs require an independent financial review and a
new Financial Owner exact-content decision. Not wired into governance. Canonical (deployed default) behaviour unchanged.

Base: PR #332 HEAD `32b9478f0e137e586df665aefd00c59a960c55d8` (previously approved six OD-R blobs).

## 1. Lifecycle and authority matrix (OD-R policy only; canonical path never enters it)

| # | Stage (owner) | Evaluation | Authoritative state | Final checks required | Evidence binding | Exception precedence |
|---|---|---|---|---|---|---|
| 1 | Input validation / policy (`apply_generic_financing_policy`) | n/a | applied inputs | none | — | structural errors raise first (unchanged) |
| 2 | Initial-DSRA seed (`run(pi)`, policy owner) | **outside OD-R** (canonical, failure swallowed as before) | none (seed only) | none | — | swallowed seed failure → funding 0 (unchanged) |
| 3 | Initial-DSRA iteration *k* (policy owner, one `OdrAttempt`) | provisional unless it converges | the returned evaluation of the converged iteration | all checks of its returned state | per attempt | DSRA non-convergence `H1_DSRA_INITIAL_FUNDING_NOT_CONVERGED` |
| 4 | U2 financing-income iteration (waterfall) | each `run_project_financing_model` is a separate financing state | only the financing actually returned in the G2C result | checks bound to that state | per financing state | `U2_*` / `Q7_IDEMPOTENCE_*` unchanged |
| 5 | Construction IDC outer loop (construction owner) | seed + every superseded outer G2A provisional | returned inner G2A after outer convergence, unfunded invariant, verification G2A, idempotence, opening-SHL identity | returned G2A {CAPACITY, FUNDED\|STRICT} + verification G2A {CAPACITY, FUNDED\|STRICT} | bound to the returned model result | `PR9_OUTER_*` unchanged, never masked |
| 6 | G2A derived-SHL/Senior fixed point (top-level when no construction) | every non-converging iteration provisional | converging iteration's passes (strict replaces funded) | {CAPACITY, FUNDED\|STRICT} | bound to its model result | `G2A_*` unchanged |
| 7 | Senior / SHL / tax fixed point (orchestrator) | inner iterations evaluate without maturity check (unchanged) | converged schedule | contributes the pass ledger | ledger per pass | `SeniorDebtNonConvergenceError` unchanged |
| 8 | Final waterfall SHL schedule (waterfall) | per financing state | the returned financing state | WATERFALL.FINAL_SHL_SCHEDULE when the returned state has an SHL liability | bound to that financing's model result | canonical immediate check outside OD-R |
| 9 | Finalization (`OdrAttempt.finalize`, policy owner) | exactly once per returned evaluation | — | derived from the returned state (below) | identity of `financing_result.project_model_result` | economic breach > contradictory > missing |
| 10 | Production authority (`run_clean_production`) | after finalization | accepted G2C | Senior maturity settlement gate (unchanged) | — | `CleanProductionRunUnavailable` wrapping |
| 11 | Persistence (`v2_atomic_run_commit`, Run History) | only after a returned result | committed Run | — | — | any earlier exception → nothing committed |

### Required final checks (applicability from the returned state, never from evidence)

| Returned financing state | G2A final roles | Waterfall final check |
|---|---|---|
| `ProjectFinancingResult` with construction financing and an SHL schedule | CONSTRUCTION_RETURNED_G2A + CONSTRUCTION_VERIFICATION_G2A | required iff SHL liability |
| `ProjectFinancingResult` without construction financing, SHL schedule | G2A | required iff SHL liability |
| No SHL schedule in the final model | none | required iff SHL liability (else NOT_APPLICABLE_NO_SHL) |
| Junior / multi-senior subclasses | none (canonical immediate check at every evaluation) | required iff SHL liability |

SHL liability = positive derived SHL cash principal, or any positive drawdown / opening / closing balance in the final SHL
schedule. A very small positive amount is a liability.

## 2. Findings

| ID | Class | Finding | Evidence | Disposition |
|---|---|---|---|---|
| E-1 | **P0** | Approved candidate accepted an OD-R Run whose **returned** financing state never had its final waterfall SHL check: cash-reserve interest + distribution accounting return the final U2 re-run financing; stale checks of earlier states satisfied the attempt-wide list (38 entries, label `PASSED`). | Real `reference-wind` + cash-reserve + distribution accounting, no injection: `32b9478f` FEASIBLE (OD-R); candidate `ODR_FINAL_EVIDENCE_MISSING: WATERFALL.FINAL_SHL_SCHEDULE`. Canonical FEASIBLE unchanged (SHL 11,674.73 kEUR). | Fixed (binding + finalization). |
| E-2 | **P0 (injected)** | Missing final waterfall registration was accepted as `NOT_APPLICABLE_NO_SHL` (applicability inferred from absence). | Correction D reproduction, real reference-wind with suppressed registration. | Fixed (applicability from state). |
| E-3 | P1 | Final G2A evidence was attempt-wide: missing returned/verification G2A, missing capacity or funded/strict pass, duplicate or misbound evidence were not structurally detected. | Fault injections in `tests/test_v9p2a_odr_finalization_contract.py`. | Fixed: required per returned state. |
| E-4 | P1 (canonical, out of scope) | Canonical waterfall returns the final U2 re-run financing while its gated SHL schedule was computed for an earlier financing state. | Same configuration as E-1. | Reported; canonical unchanged; separate financial decision. |
| E-5 | P2 | DSRA seed failure is swallowed (seed only). | Existing behaviour. | Unchanged; seed is never authority. |
| E-6 | P2 | Superseded evaluations' breaches are diagnostics only. | Existing OD-R semantics. | Unchanged; now also for superseded U2 states. |

## 3. Architecture decision

Compared: (1) minimal waterfall completeness guard; (2) typed evidence contract bound to the returned state; (3) unified
validation gate over all final financial artefacts; (4) restructuring of calculation/finalization boundaries.
(1) closes E-2 only and leaves E-1/E-3. (3) and (4) would re-touch canonical code paths without a demonstrated defect.
**(2) is implemented**: four protected files, no canonical path change, O(number of final checks) validation on already
available results, no copying or serialization.

## 4. Exact protected content (candidate commit `db92728d517b40ed48c5657f9902de06ca9d90f5`, local only)

| Protected path | Approved (Financial Owner, OD-R) | Correction E candidate | Change |
|---|---|---|---|
| `financial_engine/shl/maturity_authority.py` | `8383eb2d735f310a09d9f080134a314efb276ba6` | `b8c9b58def20116a8775145c66a9222bef526c1d` | finalization contract: state-bound evidence, `required_final_checks`, `finalize`, `OdrFinalizationError` |
| `financial_engine/financing/generic_product_policy.py` | `293d896ac474f47ea74a93ac5ac5d7a587f1446b` | `b7df63cd5be886d5971213c03f9bfff046913ae1` | DSRA owner calls `finalize(result)` before returning |
| `financial_engine/financing/project.py` | `16ab1921b539ec3ed42d55554b1392ce781e6ce5` | `e83cb580a03658b5e201c81f6ecd0a7a9aa66585` | final G2A evidence bound to the returned model result (3 call sites) |
| `financial_engine/shareholder_waterfall/model.py` | `6ab84043c0267832125a073a3a881e1e86ac0e3d` | `6e8ce1936f1d4d51b49a92be078a53f0cfe44a51` | waterfall check bound to the financing state it evaluated |
| `financial_engine/orchestrator.py` | `85c8008f2b4a656fd28eea1169689b19131576e4` | unchanged | — |
| `financial_engine/shl/production.py` | `9bb852c235a988bff994c4327b3b63dd6d77ae20` | unchanged | — |

Application `app/services/production_financial_authority.py` unchanged (`89083cd41a4de029ae3c57ee0a4f4a871c7863bd`).
No predicate, equation, tolerance, canonical branch, numerical output or golden changes. The four changed blobs require
an independent financial review and a **new** Financial Owner exact-content decision; the previous six-blob approval
remains a historical record and is not reused.

## 5. Validation (local, Windows, Python 3.12.10)

* 112-case matrix + P8 supplementary set re-executed on the candidate (canonical and OD-R): 62 / 17 / 27 / 4 / 2, zero
  defects; every verdict, financial digest, Integrity digest, exact error text and OD-R metadata identical to `32b9478f`.
* Finalization contract (`tests/test_v9p2a_odr_finalization_contract.py`): 21 passed — real-engine fault injection for
  missing waterfall / returned G2A / verification G2A / capacity / funded-or-strict / top-level G2A evidence, duplicate,
  misbound (stale) and contradictory evidence, single finalization, superseded-state diagnostics, precedence of economic
  breach over missing evidence and of upstream idempotence / non-convergence errors over missing evidence, the real P0
  cash-reserve configuration, concurrent evaluations, failure-then-success isolation; canonical unchanged under injection.
* Existing OD-R modules (final-state authority, Run-to-commit safety, proposal): 58 passed before commit.
* 33 regression suites touching the changed modules: only the four exact-content guards beyond the unmodified-main baseline.
* Governance ring: the original 25 blocking nodes unchanged, plus the two Correction B proposal tests, which correctly
  refuse to recognise the new unapproved content as the approved six blobs. Nothing is wired; no guard or pin changed.

## 6. Stage 2 (only after a new exact-content decision)

1. Record the new approved blob identities (four changed + two unchanged) in a decision record bound to exact content.
2. Implement the bounded successor (draft parked as `stash@{0}` "correction-D-draft" on the PR branch) against the newly
   approved identities, wire it through `tests/quarterly_candidate_recognition.py` and the per-successor branch of
   `tests/test_ci_acceptance.py`, with the twenty negative controls; historical pins untouched.
3. Synchronise PR #332 with current main (`b28a0572`, CI-200M) by a normal merge; re-verify all protected blobs.
4. Push to PR #332, record exact-head CI under the 200-minute budget, independent governance review, separate merge decision.
