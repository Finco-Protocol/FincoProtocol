# WF-A / RC-4 Institutional numerical and credit validation V3 (with Addendum A)

## Provenance and boundaries

Base `origin/main` `03e2b9638e9324bb18ea8420ce8f9823f4f0a676` (includes RC-UX #286). Branch `feat/model-wfa-numerical-credit-validation-v3`. One integrated Draft PR (Addendum A included, no separate PR). No approval, merge, deployment, rebase, squash or force push.

ZERO modifications to `financial_engine/`, `finco_core/`, `domain/`, `app/` production code, `app/v2/router.py`, `post_run_ui.py`, templates, static assets, tolerances, goldens, release pins or CI workflows. Release-closed features stay closed (Junior, BESS M7, M6 valuation, F4/P2, Revenue V3). Junior activation is not touched. The deliverable is a **validation workflow**, not a second project-finance engine: it recomputes identities from persisted Run evidence and compares; it never produces a number the product uses.

A successful Run is not a validation PASS, a PASS on an identity is not bankability, and no tolerance was widened to obtain a PASS.

## 1. Capability inventory and reuse

| Capability | State | Treatment |
|---|---|---|
| P0-B3 reconciliation framework (states, stages, tolerances, canonical bytes) | EXISTING / VERIFIED | reused unchanged |
| F3.9 four-vertical period identities, coverage matrix and Decimal oracles | EXISTING / VERIFIED | reused; WF-A adds only credit/impact identities on top; no F3.9 identity duplicated |
| Immutable Run History persistence (statements, debt schedule, distribution, integrity evidence) | EXISTING | read-only source |
| F2 bankability configuration (lender case, sizing mode, explicit rates) | EXISTING | stress route |
| F3 two-Senior facilities, F4 investor agreement, Revenue V2 contracts | EXISTING | Addendum A input routes |
| Independent DSCR, gearing, sized-debt, binding-label coherence and lock-up identities (`CR-*`) | MISSING → added | `tools/numerical_validation/credit.py` |
| Facility (`FT-*`), investor (`IV-*`) and contract (`RC-*`) impact identities | MISSING → added | `tools/numerical_validation/impact.py` |
| Reported-versus-independent credit matrix and directional checks | MISSING → added | `credit_matrix.py` |
| LLCR, PLCR | UNAVAILABLE | `min_llcr` is null; no discount basis is persisted; never derived |
| Event of Default mechanic, cash sweep amounts | UNAVAILABLE | not in the engine / not persisted; RAG classes are presentation, not contractual events |
| Fixed-debt re-solve (keep a sized debt under a CFADS shock) | UNAVAILABLE | only `gearing_cap` sizing keeps debt independent of CFADS |
| Independent capacity values (DSCR capacity vs gearing capacity) | UNAVAILABLE | not persisted; binding label is checked for coherence only |
| Writable P90 generation hours | UNAVAILABLE | the field registry exposes P50 only; P90 is reached through the lender case |

## 2. Credit identities

| Identity | Statement | Basis / tolerance |
|---|---|---|
| CR-GEARING-DEF | recorded gearing = Senior debt / total project uses (Sources & Uses) | full precision, ratio 1e-7 |
| CR-SIZED-DEBT | solver final debt size = Sources & Uses Senior debt (single-solve runs only; two-Senior is NOT_COMPARABLE) | full precision, terminal tolerance 1e-4 kEUR |
| CR-BINDING | binding-constraint label is coherent with recorded gearing and the cap | ratio 1e-7 |
| CR-DSCR-MIN / AVG | reported min/avg DSCR = min/mean of base CFADS / debt service where debt service > 1e-6 | full precision |
| CR-DSCR-NODS | no DSCR is reported for a period without debt service | — |
| CR-LOCKUP-FLAG | recomputed DSCR strictly below the declared lock-up threshold ⇒ gate closed; locked without a DSCR trigger ⇒ NOT_COMPARABLE (non-DSCR gate components) | strict `<`, as in the engine predicate |
| CR-LOCKUP-DIST | closed gate ⇒ zero distribution (persisted at 2dp) | 2dp half-quantum |
| CR-LOCKUP-COUNT | reported periods in lock-up = number of closed-gate periods | exact |

## 3. Credit matrix results (real committed Runs)

| Vertical | Committed / cases | Metric rows PASS | FAIL | UNAVAILABLE | NOT_COMPARABLE | Directional PASS | FAIL |
|---|---|---|---|---|---|---|---|
| solar | 24 / 26 | 144 | 0 | 0 | 0 | 56 | 0 |
| wind | 5 / 5 | 30 | 0 | 0 | 0 | 14 | 0 |
| data_center | 1 / 5 | 6 | 0 | 0 | 0 | 1 | 0 |
| ev_charging | 3 / 5 | 18 | 0 | 0 | 0 | 3 | 0 |

Per-vertical matrices (`solar` full; the other verticals reduced): committed under `docs/model_v2/wfa_matrices/`. Cases that the product refuses to commit (near-zero CFADS) are reported as **fail-closed with the typed reason**, not as validated.

Uncommitted (solar):
* `solar-Z-price-85` — These inputs leave part of the shareholder loan unpaid at its maturity, so the model did not produce a result. Review OPEX, CAPEX, revenue or shareholder-loan terms and run again. Your edits are saved; the previous Last 
* `solar-Z-price-98` — The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.

Uncommitted (data_center):
* `data_center-F0` — The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
* `data_center-R-capex+10` — These inputs leave part of the shareholder loan unpaid at its maturity, so the model did not produce a result. Review OPEX, CAPEX, revenue or shareholder-loan terms and run again. Your edits are saved; the previous Last 
* `data_center-R-opex+50` — The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
* `data_center-F-opex+50` — The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.

Uncommitted (ev_charging):
* `ev_charging-R-opex+50` — The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
* `ev_charging-F-opex+50` — The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.

## 4. Addendum A — Financial Feature Impact Matrix

Every case is a real committed Run produced through the released route; ‘independent expectation’ is recomputed from the declared inputs only. Differences are Run-minus-baseline against the unmodified Working Copy.

| Case | Family | Input modification | Activation | Verdict | PASS/FAIL/UNAVAIL | Δ Senior debt | Δ equity funding | Δ min DSCR |
|---|---|---|---|---|---|---|---|---|
| D0 | DEBT | none (single-Senior baseline) | no F3 collection | **BASELINE_VERIFIED** | 938/0/42 | 0.00 | 0.00 | 0.0000 |
| D1 | DEBT | two explicit Senior facilities (senior-a 4 %, senior-b 7 %, 12 m grace) | F3 collection activated by the Run (authority recorded) | **VERIFIED** | 1143/0/25 | -5,431.47 | 4,798.70 | 2.3582 |
| D2 | DEBT | senior-a fixed rate +100 bp | F3 collection activated by the Run (authority recorded) | **VERIFIED** | 1143/0/25 | -5,431.47 | 4,807.89 | 2.2698 |
| D3 | DEBT | senior-b grace 12 → 24 months | F3 collection activated by the Run (authority recorded) | **VERIFIED** | 1143/0/25 | -5,431.47 | 4,798.70 | 2.3339 |
| D4 | DEBT | senior-a drawdown date +31 days (commitment/draw timing) | F3 collection activated by the Run (authority recorded) | **VERIFIED** | 1143/0/25 | -5,431.47 | 4,796.35 | 2.3582 |
| D5-invalid | DEBT | negative commitment | rejected | **FAILS_CLOSED** | — | — | — | — |
| D5 | DEBT | proposal saved, activation absent | NOT activated | **INERT_IDENTICAL_TO_BASELINE** | — | 0.00 | 0.00 | 0.0000 |
| E0 | EQUITY | none | no investor agreement | **BASELINE_VERIFIED** | 938/0/42 | 0.00 | 0.00 | 0.0000 |
| E1 | EQUITY | one investor, 100 % ownership | agreement bound and reconciled by the Run | **VERIFIED** | 997/0/37 | 0.00 | 0.00 | 0.0000 |
| E2 | EQUITY | two investors 60/40 | agreement bound and reconciled by the Run | **VERIFIED** | 1054/0/37 | 0.00 | 0.00 | 0.0000 |
| E3 | EQUITY | ownership 60/40 with contributions 50/50 | agreement bound by the Run | **VERIFIED** | 1054/0/37 | 0.00 | 0.00 | 0.0000 |
| E4 | EQUITY | contribution total 5 kEUR below project funding | Run rejected | **FAILS_CLOSED** | — | — | — | — |
| E5 | EQUITY | ownership fractions not summing to 1 | rejected | **FAILS_CLOSED** | — | — | — | — |
| P0 | PPA | none (legacy single PPA) | legacy path | **BASELINE_VERIFIED** | 938/0/42 | 0.00 | 0.00 | 0.0000 |
| P1 | PPA | one fixed PPA, 100 % share | contract book saved and applied by the Run | **VERIFIED** | 1429/0/33 | 213.42 | 71.14 | 0.0180 |
| P2 | PPA | two PPAs 30 % + 30 % with residual merchant 40 % | contract book saved and applied by the Run | **VERIFIED** | 1680/0/33 | 154.53 | 51.51 | 0.0150 |
| P3 | PPA | PPA 60 % indexed 2 %/operating year + residual merchant | contract book saved and applied by the Run | **VERIFIED** | 1478/0/33 | 259.60 | 86.53 | 0.0192 |
| P4 | PPA | PPA 60 % with explicit stepped price_curve 80 / 90 / 100 EUR/MWh (one price per operating period), residual merchant 70 | Revenue V2 contract book (version 2, exact-period curve) saved and applied by the Run | **VERIFIED** | 1482/0/33 | 120.78 | 40.26 | 0.0130 |
| P5 | PPA | PPA expires mid-life; residual merchant continues | contract book saved and applied by the Run | **VERIFIED** | 1405/0/58 | 160.48 | 53.49 | 0.0153 |
| P6 | PPA | PPA + CfD overlay (strike 95 vs merchant 70) | contract book saved and applied by the Run | **VERIFIED** | 1579/0/33 | 206.80 | 68.93 | 0.0177 |
| P7 | PPA | PPA 40 % with residual merchant at 60 | contract book saved and applied by the Run | **VERIFIED** | 1483/0/33 | 81.08 | 27.03 | 0.0105 |
| P8-P50 | PPA | PPA 60 % at 60 EUR/MWh, merchant 45, lender case P_50 saved through the F2 bankability configuration | contract book + lender_case=P_50 applied by the Run | **VERIFIED** | 1486/0/33 | 14.91 | 4.97 | -0.0756 |
| P8-P90 | PPA | PPA 60 % at 60 EUR/MWh, merchant 45, lender case P90-10y saved through the F2 bankability configuration | contract book + lender_case=P90-10y applied by the Run | **VERIFIED** | 1489/0/33 | -24.79 | -8.26 | 0.0021 |
| P8-compare | PPA | same PPA downside contract book, lender case P_50 then P90-10y | both lender cases saved and executed | **VERIFIED_PAIRED_COMPARISON** | — | — | — | — |
| P9-negative_price | PPA | negative_price | rejected | **FAILS_CLOSED** | — | — | — | — |
| P9-share_over_100 | PPA | share_over_100 | rejected | **FAILS_CLOSED** | — | — | — | — |
| P9-unknown_type | PPA | unknown_type | rejected | **FAILS_CLOSED** | — | — | — | — |
| P9-window_off_period_boundary | PPA | window_off_period_boundary | rejected | **FAILS_CLOSED** | — | — | — | — |

Reading the matrix:
* **Add Debt** — D1–D4 change the Run only when the proposal is *activated by the Run*; D5 shows a saved-but-not-activated proposal leaves every result identical and records no facility authority; an invalid proposal persists nothing. IDC, commitment fee, upfront fee, operating interest, level principal and maturity are recomputed independently (residuals ≤ 3e-15).
* **Add Equity** — ownership allocation and actual funding are separate: E1–E3 leave Senior debt and equity funding identical to baseline; actual funding is determined by project financing / Sources & Uses. A contribution total that does not match project funding cannot commit a Run (E4).
* **Add PPA** — price, indexation (by operating year), allocation, residual merchant, CfD settlement and window are recomputed per period. Debt re-sizes to the changed CFADS or the gearing cap; direction is not asserted (see finding F-3).

## 4a. Case-level verdict integrity (Correction A)

A case is **VERIFIED** only when every feature-specific identity that applies to it (`FT-*` for Add Debt, `IV-*` for Add Equity, `RC-*` for Add PPA) has at least one PASS and no FAIL, UNAVAILABLE or NOT_COMPARABLE outcome. Passing F3.9 statement identities never contribute. Baselines are **BASELINE_VERIFIED** (no claim that an inapplicable feature was validated); an inert case is **INERT_IDENTICAL_TO_BASELINE**; a missing or unavailable required identity yields **INCOMPLETE_FEATURE_IDENTITIES_NOT_EVALUATED**; a NOT_COMPARABLE required identity stays **NOT_COMPARABLE**, distinct from FAIL. Regression: `test_case_verdict_requires_feature_specific_identities` (800 existing PASS results but no feature checks cannot be VERIFIED). Run identities (run key, snapshot id, composite hash) are now recorded for every baseline and modified Run.

### P4 — scheduled / stepped PPA (Revenue V2 exact-period curve)

Executed on a committed Run (`1873d76906c2`): version-2 contract book, PPA 60 % with an explicit price at each of 50 operating-period starts (declared steps [80.0, 90.0, 100.0] EUR/MWh, no indexation, no interpolation), residual merchant 70. Verdict **VERIFIED**; `RC-PRICE` reconciles every period and at least three distinct declared prices were reproduced.

### P8 — P50 versus P90-10y lender case (paired Runs)

Same PPA downside contract book (60 % at 60, merchant 45); lender case saved through the F2 bankability configuration and executed twice. P50 Run `5a10b764f517`, P90-10y Run `18185c7bc565` (distinct run keys, snapshots and composite hashes). The saved configuration was read back for each case.

| Metric | P50 | P90-10y |
|---|---|---|
| dscr_debt_capacity_keur | 8,740.9271 | 7,899.9458 |
| final_senior_commitment_keur | 6,746.3787 | 6,706.6784 |
| binding_constraint | GEARING | GEARING |
| min_dscr | 1.2000 | 1.2777 |
| equity_irr | 0.2187 | 0.2598 |

Generation and total EBITDA are identical across the two Runs (lender assumptions are separate from the operating case); only DSCR capacity and the sized debt differ. Gearing is the binding constraint in both, so the sized debt moves only through uses (finding F-3). **NOT COMPARABLE:** CFADS-at-P90 is not persisted as a separate series (the P90 sizing CFADS is internal to the solver); only its effect on DSCR capacity and sized debt is observable.

## 5. Findings

| ID | Finding | Classification |
|---|---|---|
| F-1 | `flat_dscr_sculpted` still applies the gearing cap, so it behaves like the default combined minimum; there is no pure DSCR-only sizing route. | potential defect / ambiguity — FINANCIAL AUTHORITY REVIEW REQUIRED (naming vs behaviour) |
| F-2 | Under fixed-debt (`gearing_cap`) stress a DSCR below 1.0 is still reported as CONVERGED; the feasibility check is a documented deferral (`SENIOR_DEBT_GEARING_SCULPTING.md`). | documented deferral — unvalidated assumption |
| F-3 | When the gearing cap binds, debt = gearing × uses and uses move with initial DSRA, IDC and fees; a revenue shock can therefore move debt in the ‘wrong’ direction (e.g. price −30 %: 6769.6 → 6883.3). Expectations in the matrix are conditional and explained, never asserted blindly. | explained mechanic — verify intent |
| F-4 | Operating-year indexation groups `per_year` consecutive operating periods from the first one; a stub first period counts as a full bucket, so the first indexation step arrives after ~10 months in the sample, not on a 12-month anniversary or calendar year. | convention — REQUIRES FINANCIAL APPROVAL against contract practice |
| F-5 | Equity IRR is null under fixed-debt stress in every case. | UNAVAILABLE — not derived |
| F-6 | LLCR / PLCR / Event of Default / cash sweep are not computed or persisted. | UNAVAILABLE |
| F-7 | P90 generation hours are not editable; the lender case selects P90-10y while the operating case stays P50. | limitation |
| F-8 | Extreme price cuts (×0.15, ×0.02) and target DSCR 1.0 fail closed (shareholder loan unpaid at maturity / integrity stop). | fails closed — correct behaviour |

No finding is auto-corrected and no production behaviour was changed.

## 6. Verification commands

```
FINCO_MODEL_EXECUTION_MODE=thread pytest tests/test_wfa_credit_validation.py tests/test_wfa_impact_validation.py
WFA_REPORT_DIR=<dir> FINCO_MODEL_EXECUTION_MODE=thread pytest tests/wfa_generate_reports.py   # regenerates the matrices
```
