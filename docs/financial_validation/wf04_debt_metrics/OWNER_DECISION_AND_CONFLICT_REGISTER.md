# WF-04 — Owner decision and conflict register

Basis `main` `b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3`, 2026-10-29. Provenance classes: **B** = already binding Owner policy (V3 decision, the low-DSCR Run addendum, or the signed selections of the unified prompt §0A);
**R** = reviewer recommendation that this PR adopts; **S** = fact established from the source in this execution; **U** = unresolved / not approved.
Private reference material (workbooks, screenshots) is not quoted or reproduced here; it informed layout and vocabulary only.

## 1 — Conflicts between the instruction sources, and how each was resolved

| # | Conflict | Resolution in this PR | Basis |
|---|---|---|---|
| C1 | Earlier V2 text asked for **three** DSCR thresholds (default, covenant, EoD). V3 says **exactly two** inputs. | Two registry inputs only (`debt.contract.min_dscr_eod`, `debt.contract.contractual_dscr`). No third field, no default, no ordering rule between them. | **B** (V3 §1; unified prompt §0A "V3 two-input EoD rule overrides earlier three-threshold proposals") |
| C2 | The review package labelled WF-04 "study only / ask again". The unified prompt §0A supersedes it for the bounded work. | Implemented in one PR without a second Owner signature; every protected path is itemised in `OWNER_PROTECTED_PATH_EXECUTION_LEDGER.md`. | **B** (§0A) |
| C3 | `QM-COV-001` (legacy "minimum DSCR covenant not supplied") would contradict a Run that records a Contractual DSCR. | Run-bound `CD-COV-DSCR` supersedes the not-supplied row **only** when that Run recorded a Contractual DSCR; `QM-COV-001`/`QM-COV-004` keep their legacy `ProjectTerms` semantics otherwise (so no ordering between the two inputs is imposed). | **R** + **S** |
| C4 | The package's candidate `credit_decision_projection` diff used adaptive display only; the Owner asks that `0.9951` must not read `1.00x`. | Adaptive ratio display (`format_ratio`, `format_delta_x`, `format_relative_pct`) wired into the credit projection and the React views; decisions never use display strings. | **B** (low-DSCR addendum) |
| C5 | The prompt's "Contractual DSCR" may be a sizing target in some workbooks. | Sizing target (`target_dscr`, sculpting targets, `lockup_dscr`, `min_llcr`) stays an independent existing control, is shown as a labelled **Sizing assumption – not a covenant** row, and is never reused as either contractual value. | **B** (V3 §1 "do not silently repurpose an engine field") |
| C6 | #397 (Save All) is an active parallel branch; the prompt forbids a second writer and any edit to #397's branch. | The two inputs ride the **existing** authorised per-field writer and the **existing** batch writer, so #397's scalar-cell Save All carries them without integration code. #397's branch was never read-modified or pushed. Combined UI acceptance is **NOT RUN**. | **B** (§0A dependency strategy) |

## 2 — Signed selections applied

| Selection | Applied as | Verified by |
|---|---|---|
| **O1(a)** | A Run with DSCR < 1.00x remains an executable, committed, completed Run; no technical refusal for coverage. | `test_wf04_credit_debt_metrics::test_owner_example_…`, parity: weak-coverage Run commits exactly one history row |
| **O2(none)** | No added blocking/transition rule on Save or Run for low DSCR. | Save-never-runs tests; no router/CSRF/CAS change |
| **O3(credit observation only)** | Coverage deficiency, covenant breach and EoD condition are Credit-axis observations; they never change Run status or the Integrity status. | three-axis chips; Integrity block untouched |
| **O4(deferred new signing schema)** | Certificate v1 untouched; no integrity-attestation field added. | `app/export`, certificate modules not in the diff; certificate tests in the regression run |
| **O5(no unsupported bankability PASS)** | No PASS/"bankable"/"feasible" wording is produced; unprovable conclusions are `UNAVAILABLE`. | banned-word scans (unit + browser) |
| **O6(b)** | Negative-balance Integrity checks (e.g. distribution account, `NO_UNFUNDED_CASH_DEFICIT`) preserved. | `app/run_integrity/**` not in the diff; adversarial replay in `INDEPENDENT_ORACLE_AND_PARITY.md` |
| **D-A** | Presentation/status separation only; no Integrity predicate or overall removed. | zero diff under `app/run_integrity/` |
| **D-B** | Coverage on **base-case CFADS**; the lender (bank) case is reported separately and never decides a verdict. | `test_bank_case_is_reported_separately_and_never_decides_the_verdicts` |
| **D-C** | SHL `CAPACITY/FUNDED`, OD-R, POC-IV left untouched. | before/after parity incl. the low-gearing refusal band |
| **D-D** | Returns are `UNAVAILABLE` when the Run withholds them; nothing is synthesised. | unchanged returns projection |

## 3 — The three axes (Run / Integrity / Credit)

| Axis | Source | Values this PR can show | Never |
|---|---|---|---|
| **Run** | `COMPLETED`/`REFUSED` + `CURRENT`/`STALE`/historical (existing runtime authority) | unchanged | influenced by any DSCR value |
| **Integrity** | existing sealed `run_integrity_checks` (arithmetic, structural, balance, sculpting, evidence-digest) | `PASS` / `FAIL` / `INCOMPLETE` / `UNAVAILABLE`, shown verbatim | altered, hidden or downgraded because coverage is low |
| **Credit** | this PR: coverage (< 1.00x), covenant (< Contractual DSCR), EoD condition (< Minimum DSCR), lock-up observation, sizing-target observation | `DEFICIENCY` / `NO_DEFICIENCY_FOUND`, `BREACHED` / `COMPLIANT`, `TRIGGERED` / `NOT_TRIGGERED_UNDER_THIS_FLOOR`, `NOT_CONFIGURED`, `UNAVAILABLE`, `NOT_APPLICABLE` | a payment-default, cure/grace, acceleration, legal-default, profitability or bankability statement |

## 4 — Still not approved / deferred (U)

| Item | Why it stays open | Handling here |
|---|---|---|
| **Test frequency / testing convention of a real facility agreement** (every model period vs a rolling annual ratio, calculation-date cut-offs) | No legal convention was supplied; there is no third input to configure it. | Run's own calendar is used and disclosed in `test_basis` as `FINCO_MODEL_CONVENTION_NOT_A_LEGAL_TEST`; this is the **one** classification that cannot be asserted as a legal test. |
| Reserve draw / unpaid scheduled service | A Run does not persist DSRA draw, required DSRA, DSRF drawings or a payment ledger. | `UNAVAILABLE` with the exact missing evidence listed in the payload and on screen. |
| Per-period LLCR/PLCR series | Persisted only as an aggregate minimum. | Chart/table show `UNAVAILABLE` with reason; no series is fabricated. |
| Lock-up threshold value | Only the per-period `lockup_active` flag is persisted. | Shown as an observation with its flags, not a threshold. |
| Signed-certificate vN+1 / integrity attestation | Separate Owner gate (O4). | OPEN; v1 artefacts unchanged and still valid. |
| Legal cure/grace/waiver/acceleration, legal declaration of default | Out of scope (§8). | Never produced; the UI states the opposite explicitly. |
| `GEARING_CAP`, SHL CAPACITY/FUNDED/OD-R/B2, reserves/DSRF, cash sweep, maturity, native V10/V11 | Separate methodology + oracle required (§8). | No change; not run (`runtime_compilation_authorized: false`). |
| Combined Save All + Debt Metrics browser acceptance | Needs #397 merged. | **NOT RUN**; forward-integration note in `TWO_DSCR_CONTRACT_MAPPING.md` §2. |
| POC-IV | remains **NO-GO** | unchanged |

## 5 — Source-backed corrections to the supplied prompt/package

1. `min_dscr_covenant` is not a persisted input anywhere in `main`. It exists only on the evidence dataclass `ProjectTerms`; `terms_from_project_inputs()` never fills it (see mapping §1). The credit projection therefore always reported "not supplied" — now replaced, per Run, by the recorded value.
2. The unified prompt names `app/api/project_runner.py`, `app/v2/react_workspace_router.py` and `app/workbook/bankability_config.py` as possible owned call-sites. P00 proved none is needed (the existing credit-decision route already carries the new `debt_metrics` block), so none was touched.
