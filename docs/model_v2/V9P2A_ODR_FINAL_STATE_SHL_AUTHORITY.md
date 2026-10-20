# V9-P2a — Final-State SHL Maturity Authority (OD-R)

Release-closed financial-authority candidate. **Not approved, not activated, not released.**
Base: `main` `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` (RC-7C). Policy approval: Financial Owner
decision OD-R (policy only — it does not approve these exact protected blobs).

## 1. What changes and what does not

The cash-sweep SHL maturity predicate `closing > convergence_tolerance_keur + 1e-9` at the contractual
maturity period and its exception `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` are unchanged, as is every
calculation (opening, interest, PIK, principal, service, closing; Senior sizing/sculpting; Sources &
Uses; tax/CFADS and interest limitation; DSRA; construction IDC; terminal classification; statements;
Integrity). OD-R changes only **when** a breach of the predicate is a financial rejection.

| Evaluation | Canonical (deployed default) | OD-R candidate |
|---|---|---|
| Any provisional G2A iteration pass | reject | record diagnostic |
| Construction seed / superseded outer-iteration G2A | reject | record diagnostic |
| Superseded initial-DSRA iteration (whole engine evaluation) | reject | record diagnostic |
| Returned converged G2A: final DSCR-only capacity pass | reject | **reject** |
| Returned converged G2A: final funded pass, or the strict re-solve that replaced it | reject | **reject** |
| Construction idempotence-verification G2A: same two passes | reject | **reject** |
| Final waterfall SHL schedule (returned evaluation) | reject | **reject** |
| DSRA seed run (existing swallowed-failure seed) | swallowed | swallowed (unchanged) |

Final checks are decided only after every existing convergence, unfunded-at-convergence and
idempotence validation has succeeded, and before a result can be returned to the production
authority, the policy-run memo, or Run persistence.

## 2. Authority propagation (explicit, lifecycle-owned)

* `financial_engine/shl/maturity_authority.py` (new): typed `ShlMaturityContext(PROVISIONAL|AUTHORITATIVE, ledger)`,
  `ShlMaturityShortfall`, per-invocation `G2aShlMaturityEvidence`, per-evaluation `OdrAttempt`, evidence summary.
* **SHL kernel** `compute_shareholder_loan_schedules(..., maturity_context=None)`: `None`/AUTHORITATIVE = canonical raise
  (identical message). PROVISIONAL records the breach in the ledger and continues the same arithmetic. No second kernel.
* **Orchestrator** `run_senior_debt_model(inputs, *, shl_maturity_context=None)` passes the context to the two schedules on
  the converged Senior/SHL/tax state (handshake probe and final SHL schedule). It is not an input field, not part of the
  fingerprint; the SHL/tax fixed-point iterations already evaluate without the check (unchanged).
* **G2A** (`run_project_financing_model`): only inside an OD-R evaluation, each capacity / funded / strict pass gets its own
  provisional context. At the `break` of the converging iteration its passes become the *final passes* (strict replaces
  funded). Authority follows the solver lifecycle (the convergence branch), never iteration numbers, amounts, proximity or
  cache hits.
* **Construction IDC owner**: the seed G2A and every superseded outer-iteration G2A are absorbed as provisional; after outer
  convergence and the unfunded invariant, the returned inner G2A's final passes are final; the verification G2A's final
  passes are final; then the existing idempotence check runs.
* **Waterfall**: inside an OD-R evaluation the gated SHL schedule's check is recorded as the final check
  `WATERFALL.FINAL_SHL_SCHEDULE`; outside it is the canonical immediate check.
* **Initial-DSRA owner** (`run_with_generic_financing_policy`): each engine evaluation is one `OdrAttempt`
  (context-local `ContextVar`, opened only here, nesting refused, reset in `finally`). A superseded evaluation is demoted to
  diagnostics; the returned evaluation must have zero failed final checks, otherwise the canonical error is raised.
* **Exception precedence**: if any exception escapes an evaluation in which a final check had already failed, the maturity
  error is raised (chained) — exactly what the canonical engine would have raised first. Otherwise the exception propagates
  unchanged. Structural, numerical and all other exceptions are never converted into success.

Absent an OD-R evaluation (every product Run, every thread or worker process without one) all of the above is the canonical
path; a leaked context can only be absent, which is the stricter behaviour.

## 3. Release-closed selector and provenance

`GenericFinancingPolicy.shl_maturity_authority` — default `CANONICAL_EVERY_EVALUATION`; candidate
`OD_R_FINAL_STATE_SHL_MATURITY_V1`; unknown values fail closed (`H1_UNKNOWN_SHL_MATURITY_AUTHORITY`). No product module
constructs or passes a financing policy (`run_clean_production(financing_policy=None)` → canonical default); this is
asserted by test. The policy-run memo key includes `repr(policy)`, so canonical and OD-R results can never be shared.

Provenance: only an OD-R run returns `OdrFinancingPolicyEvidence` (subclass; canonical `FinancingPolicyEvidence` unchanged
field-for-field) and adds `shl_maturity_*` keys to `authority_metadata` (authority id, provisional violation count, maximum
provisional shortfall, final checks performed, final waterfall check, superseded DSRA attempts). No persistence schema change;
no engine version change (no number changes); historical Runs are never recomputed.

Rejection evidence: original code, final-state shortfall, plus
`; od_r_final_check=<check>; od_r_failed_final_checks=<n>; od_r_provisional_violations=<n>`.

## 4. Financial acceptance (112 cases) — `V9P2A_ODR_ACCEPTANCE_EVIDENCE.json`

| Class | Research | Candidate |
|---|---:|---:|
| Previously feasible (full output + Integrity bit-identical) | 62 | 62 / 62 |
| Provisional-only failures now feasible | 17 | 17 / 17 |
| Final-state economically infeasible (same code, final evidence) | 27 | 27 / 27 |
| Structural / input rejections (identical error text) | 4 | 4 / 4 |
| Numerical / degenerate rejections (identical error text) | 2 | 2 / 2 |

Per-case verdicts equal the research per case. Three SHL seeds (zero, gearing, 0.5×gearing; research-only probe on a scratch
copy, never committed): zero verdict differences; outputs differ for 54 / 40 feasible cases exactly as in the research.

Supplementary P8 (interest limitation enabled; bullet SHL): all canonical-feasible cases bit-identical; IL admissions pass
Integrity; bullet SHL is outside the cash-sweep predicate and unchanged.

## 5. Changed rejection outcomes (complete statement)

1. The 17 provisional-only cases change from `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` (provisional estimate) to FEASIBLE.
2. The 27 final-state rejections keep the code; the reported closing balance is now the final-state shortfall (previously the
   first provisional breach) and the message carries the OD-R suffix.
3. A case whose only breaches are provisional and which then fails a numerical validation now reports that numerical error
   (e.g. `G2A_SHL_SENIOR_FIXED_POINT_DID_NOT_CONVERGE`) instead of the provisional maturity breach. Still rejected.
   Not observed in the 112-case matrix; demonstrated only by the capped-iteration negative controls.
4. No previously feasible case changes; no structural/numerical rejection text changes.

## 6. Disclosures (pre-existing, unchanged, not addressed here)

* Senior terminal label: residuals between the 1e-7 kEUR classification and 1e-4 kEUR settlement thresholds keep
  `OUTSTANDING_AT_MATURITY` (6 canonical previously-feasible Runs; 6 admitted Runs, max 2.9e-5 kEUR ≈ €0.03). Never relabelled;
  separate Financial Owner decision.
* Integrity `BALANCE_SHEET_BALANCES` FAIL on three equity-only synthetic cases on canonical main and identically under OD-R.

## 7. Governance

Protected-content changes and candidate blobs: `tests/v9p2a_odr_candidate_proposal.py` (proposal only; not imported by any
current-authority guard; every approval state `False`). The RC-7C exact-content recognition and dependent pin guards
legitimately fail on this branch until an owner-attested, independently reviewed successor adopts the exact blobs.
No guard, pin, protected-path list, tolerance or golden was changed.

Required before any activation: independent financial review; Financial Owner approval of the exact protected blobs; a separate
release decision opening the selector on a controlled path. V9-P2b (OD-1, solver/performance work) is out of scope.
