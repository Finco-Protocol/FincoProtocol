# V9-P2a / OD-R — Correction F: Complete Final Financial Evidence Contract

**Status: UNAPPROVED financial candidate, local only (`local/v9p2a-correction-e`, commit `971aa4f1`).**
Not pushed, not wired into governance, no owner approval claimed. Canonical (deployed default) behaviour unchanged.
Base chain: PR #332 `32b9478f` (approved six blobs) → Correction E `db92728d` / `a32ad575` → Correction F `971aa4f1`.

The independent review `FINCO_PR332_CORRECTION_E_INDEPENDENT_FINANCIAL_REVIEW_2026-10-21.md` was not available on the
implementation machine; the four P1 findings were taken from the Correction F brief and each was reproduced against the
actual Correction E code before being corrected.

## 1. Findings → implementation → tests

| Finding | Root cause in Correction E | Correction F | Real-engine controls (`tests/test_v9p2a_odr_finalization_contract.py`) |
|---|---|---|---|
| **P1-01** evidence identity | evidence keyed on the Python identity of `project_model_result`; a different financing sharing that model, a changed principal or schedule, or a mutated object still matched | `financial_state_digest`: deterministic SHA-256 of every `ProjectFinancingResult` field (structure, Senior and SHL principal, construction / IDC / funding, DSRA, SHL model input, cash-reserve and financing-income schedules) and the financing-dependent final model parts (Senior, SHL, post-Senior cash, tax/CFADS, cash DSRA, debt sizing, axis contract); exact IEEE-754 bits, ordered fields, sorted mappings; unknown value types fail closed. Bound at registration, **recomputed at finalization** | other financing sharing the model; same model with changed SHL principal; changed cash-reserve / financing-income schedule; mutation after registration (frozen dataclass bypassed); other-attempt / superseded / provisional evidence; **positive**: deep-copied (all objects different) result accepted |
| **P1-02** G2A sites | any site name inside a required role became a check | fixed roles (`CONSTRUCTION_RETURNED_G2A`, `CONSTRUCTION_VERIFICATION_G2A`, `G2A`); per required role exactly one `CAPACITY` and one of `FUNDED`/`STRICT`; unknown sites, extra or duplicate passes, unknown roles and roles that evaluated SHL for a structure that needs none are rejected | unknown site; extra CAPACITY; FUNDED+STRICT; missing CAPACITY / FUNDED; missing returned / verification / top-level G2A; unexpected role; unknown role; unbound evidence |
| **P1-03** waterfall provenance | bare list of shortfalls per model object | each registration carries its **proof token** (the maturity context the kernel evaluated), the digest of the exact SHL input and gated cash, the checked schedule up to maturity and the outcome. Finalization requires a check whose state digest equals the returned financing **and** whose schedule equals the returned waterfall rows (closing, gross interest, principal; bit-exact). Identical repeats (separate tokens, same inputs, schedule and outcome) are legitimate; the same token twice is `DUPLICATE`; same returned schedule with different inputs is `CONTRADICTORY`; a different schedule is stale (`MISSING … no check evaluated the returned SHL schedule`) | missing registration; re-registered proof; legitimate identical repeat (accepted, bit-identical); changed-input repeat; stale schedule (1e-6 kEUR); other financing state; context-less evidence; waterfall evidence for a no-liability state |
| **P1-04** subtype authority | `type(...) is not ProjectFinancingResult` exempted every subclass | exact-type table: `ProjectFinancingResult` → deferred G2A; `JuniorFinancingResult` → delegated canonical (Junior never passes a maturity context: every SHL check inside it is the canonical immediate check); `MultiSeniorFinancingResult` → only without SHL liability; any subclass / unknown type → `ODR_UNSUPPORTED_FINANCING`; financing carrying post-evaluation U2 cash-reserve schedules → `ODR_UNSUPPORTED_FINANCING` | exact-type table incl. two unreviewed subclasses and multi-senior with/without SHL; **real Junior engine**: all Junior Senior/SHL/tax evaluations carry no context and OD-R output = canonical |

Precedence (unchanged in substance): unsupported financing / unidentifiable state → economic breach at a required final
check (`SHL_MATURITY_RESIDUAL_FAILS_CLOSED`) → contradictory / unknown evidence → missing evidence. Upstream convergence,
idempotence and structural errors escape the evaluation unchanged (finalization never runs).

## 2. Evidence-state schema

```
OdrAttempt (one engine evaluation, context-local, opened only by the DSRA owner)
  _G2aRegistration      role ∈ {CONSTRUCTION_RETURNED_G2A, CONSTRUCTION_VERIFICATION_G2A, G2A}
                        sites: ((site, shortfall|None), ...)       state: financial_state_digest(returned financing)
                        token: the G2aShlMaturityEvidence object (registered once)
  _WaterfallRegistration state: financial_state_digest(evaluated financing)
                        inputs: sha256(SHL model input, gated cash vector)
                        maturity_period_index, repayment_mode
                        rows: ((period, closing, gross interest, principal) ≤ maturity)
                        shortfall: first breach of the unchanged predicate | None
                        token: the evaluated ShlMaturityContext (registered once)
finalize(result) once: requirements = required_final_checks(result) (exact type, SHL liability from the state)
                       state = financial_state_digest(result.financing_result)   (fresh)
                       accepted evidence = registrations with that state (+ waterfall rows equal to the returned rows)
```

## 3. Changed files (vs approved `32b9478f`)

| File | Approved blob | Correction F blob |
|---|---|---|
| `financial_engine/shl/maturity_authority.py` | `8383eb2d735f310a09d9f080134a314efb276ba6` | `a7e52bf1baab89434eedfbf32502c640f3af624d` |
| `financial_engine/financing/generic_product_policy.py` | `293d896ac474f47ea74a93ac5ac5d7a587f1446b` | `b7df63cd5be886d5971213c03f9bfff046913ae1` |
| `financial_engine/financing/project.py` | `16ab1921b539ec3ed42d55554b1392ce781e6ce5` | `3bc6c097b218d27be216cdd86133f2772a82ad70` |
| `financial_engine/shareholder_waterfall/model.py` | `6ab84043c0267832125a073a3a881e1e86ac0e3d` | `9520b09b135c7fe39d3d4fac6a0c2462b7c1c4ca` |
| `financial_engine/orchestrator.py` | `85c8008f2b4a656fd28eea1169689b19131576e4` | unchanged |
| `financial_engine/shl/production.py` | `9bb852c235a988bff994c4327b3b63dd6d77ae20` | unchanged |
| `app/services/production_financial_authority.py` | `89083cd41a4de029ae3c57ee0a4f4a871c7863bd` | unchanged |

Tests: `tests/test_v9p2a_odr_finalization_contract.py` (rewritten, 39 tests), `tests/test_v9p2a_odr_final_state_authority.py`
(two unit tests moved to the bound-evidence API). No guard, pin, tolerance, golden, predicate or canonical branch changed.

## 4. Local validation (Windows, Python 3.12.10)

| Suite | Result |
|---|---|
| 112-case matrix + P8, canonical and OD-R, executed on Correction F | 62 / 17 / 27 / 4 / 2, zero defects; **identical to the approved candidate**: verdicts, financial digests, Integrity digests, full-object digests, exact error texts, OD-R metadata |
| Final evidence contract (P1-01…P1-04, P0, precedence, isolation, Junior) | 39 / 39 passed |
| Existing OD-R modules (final-state authority, Run-to-commit safety, proposal) | 56 passed, 2 expected failures: the standalone Correction B proposal correctly refuses the new unapproved content as the approved six blobs (`content_matches_proposal() is False`); not repinned |
| 33 regression suites touching the changed modules | only the four exact-content guards beyond the unmodified-main baseline |
| Governance ring | 27 failures = the original 25 blocking nodes + the 2 proposal tests; identical set to Correction E; nothing wired |

Overhead of the contract (high-resolution wall clock, median of 3, real OD-R Runs): DC 14 ms (1.5 %), reference-solar
21 ms (0.95 %), reference-wind 20 ms (0.74 %), W25 27 ms (0.40 %), X-W25-dscr2.5 21 ms (0.80 %), S16 20 ms (0.09 %).

## 5. Separate canonical defect (not corrected here)

**C-1 (P1, canonical).** With cash-reserve interest **and** distribution accounting enabled, the canonical waterfall returns
the final U2 re-run financing (`_financing2`) while the returned waterfall rows do not correspond to any gated SHL schedule
evaluated in the Run. Real `reference-wind` + both policies: 22 financing evaluations, 16 gated SHL schedules; returned rows
differ from every one of them by ≈ 11,670 kEUR (the full SHL balance); returned financing ≠ last checked financing (cash
available for SHL differs by 1.8e-8 kEUR; principal and Senior identical); Run Integrity **FAIL**
(`SPONSOR_RETURN_INPUTS_RECONCILE`). `run_clean_production` accepts it. Reachability: only persisted / imported inputs that
set both policies (no product factory sets them). Recommended gate: refuse this configuration at the production authority
(or correct the U2 final pass) under a separate Financial Owner decision before any such project can be committed. Under
OD-R it is now refused (`ODR_UNSUPPORTED_FINANCING`).

## 6. Remaining risks

* P1 (separate decision): C-1 above.
* P2: the DSRA seed run remains canonical with a swallowed failure (seed only, never authority).
* P2: Senior `OUTSTANDING_AT_MATURITY` label below the 1e-4 kEUR settlement threshold and three equity-only Integrity
  `BALANCE_SHEET_BALANCES` failures are pre-existing and unchanged.
* The state digest excludes operating schedules and provenance text by design (not financing-dependent); a reviewer should
  confirm this boundary.

## 7. Recommended sequence

1. Independent financial review of `971aa4f1` (four changed blobs) against this report and the review bundle.
2. New Financial Owner exact-content decision for the four changed blobs (the six-blob approval stays historical).
3. Separate decision on C-1.
4. Then Stage 2: bounded governance successor bound to the newly approved identities, normal merge of current main
   (`591ea192`), push to PR #332, exact-head CI under the 200-minute budget, independent governance review.
5. Performance work (B1, OD-1 joint/warm solver) stays in V9-P2b.
