# Diagnostics Correctness V3 (RC-6 / WF-04)

Read-only correction of Diagnostics V2 evidence handling. No engine, writer, Run History, Quality registry/score, tolerance or router change. Base: `main` `97c5286a`.

## Defect matrix (each reproduced by a failing test before the fix)

| # | Check | Reproduction | Expected | Observed (before) | Consequence | Correction | Regression test |
|---|---|---|---|---|---|---|---|
| 1 | DX-CAPEX-001 | first construction period has no `uses` | later periods UNAVAILABLE | later period **PASS** with `observed = NaN` | a PASS built on missing evidence | once a period is missing, later cumulative values are `UNAVAILABLE` (`CUMULATIVE_BASE_UNAVAILABLE_AFTER_MISSING_PERIOD`) | `test_a_missing_construction_period…` |
| 2 | DX-CAPEX-001 | a construction period occurs twice | evidence defect | **FAIL** with a financial residual (summed twice) | duplicate evidence reported as a funding residual | `UNAVAILABLE` (`DUPLICATE_PERIOD_IN_COMMITTED_EVIDENCE`) | `test_a_duplicate_committed_construction_period…` |
| 3 | DX-DIST-001 | distribution schedule rows dated differently | `UNAVAILABLE` (module rule: join by index AND equal dates) | **PASS** | incompatible-date join accepted | `_same_dates` over cash waterfall, distribution and sponsor rows (`DISTRIBUTION_DATES_DISAGREE`) | `test_a_distribution_schedule_with_incompatible_dates…` |
| 4 | DX-RES-001, DX-DEP-001, DX-SHL-001 | balance-sheet evidence dated differently from the statement period | `UNAVAILABLE` | evaluated | same | date compatibility added to the three joins | `test_a_balance_sheet_row_dated_differently…` |
| 5 | DX-RES-001 | an unexplained movement equal to the Financial Close DSRA funding in a later period | FAIL (coincidence is not evidence) | **PASS** ("explained") | numerical match treated as proof | explanation allowed only at the first committed operating period | `test_initial_funding_explains_only_the_first_operating_period` |
| 6 | Root cause (DX-SHL-002 WARNING) | status warning with residual 0.00 inside tolerance | state that it reconciles; the warning is a status | "does not close … residual 0.00 against tolerance" | false mismatch claim | within-tolerance statement; no coincidence hunting inside tolerance | `test_a_status_warning_inside_tolerance…` |
| 7 | Bankability | `senior_debt.periods` has a repeated period index | excluded and listed | both rows used (minimum headroom from either) | ambiguous DSCR | duplicates excluded, listed in `duplicate_debt_periods_excluded` | `test_duplicate_senior_debt_periods…` |
| 8 | Run comparison | Runs from different engine versions or scenarios | visibly qualified | classified with no qualification | incomparable Runs read as comparable | per-candidate `qualifications` (`ENGINE_VERSION_DIFFERS/UNKNOWN`, `DIFFERENT_SCENARIO_CONTEXT`) rendered above the table; classification names unchanged | `test_comparison_qualifications…`, template test |

Checked and found correct (no change): thresholds are bound only for a CURRENT Run (STALE gets empty terms); reserve regime is dropped for non-CURRENT Runs; missing/UNAVAILABLE on either side is never "resolved"; explicit zero vs missing; invalid digest; cash DSRA vs standby DSRF; aggregate-only findings are not repeated per period.

## Remaining evidence gaps (documented, not worked around)

Fixed-asset additions/disposals; closing cash roll-forward; LLCR by period; MRA/other reserve instruments; per-period spending by calendar date; scalar inputs per Run (needed to explain input-driven differences).
