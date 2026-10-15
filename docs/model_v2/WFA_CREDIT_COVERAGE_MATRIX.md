# WF-A credit coverage matrix (CR-*, DEBT-*, FT-*)

| Identity | Stage | data_center/baseline | ev_charging/baseline | solar/baseline | wind/baseline |
|---|---|---|---|---|---|
| CR-BINDING | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-DSCR-AVG | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-DSCR-MIN | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-DSCR-NODS | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-GEARING-DEF | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-LOCKUP-COUNT | cfads_waterfall | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-LOCKUP-DIST | cfads_waterfall | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-LOCKUP-FLAG | cfads_waterfall | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| CR-SIZED-DEBT | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-CHAIN | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-DSCR | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-FIRST-OPENING | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-INTEREST | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-NONNEGATIVE | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-PRINCIPAL-TOTAL | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-ROLLFORWARD | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-SERVICE | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-STATEMENT-BALANCE | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-STATEMENT-INTEREST | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-STATEMENT-PRINCIPAL | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-STATEMENT-SERVICE | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |
| DEBT-TOTAL-SERVICE | debt | VERIFIED | VERIFIED | VERIFIED | VERIFIED |

## Outcome totals

| Configuration | PASS | FAIL | UNAVAILABLE | NOT_COMPARABLE |
|---|---|---|---|---|
| data_center/baseline | 797 | 0 | 27 | 0 |
| ev_charging/baseline | 718 | 0 | 25 | 0 |
| solar/baseline | 975 | 0 | 26 | 0 |
| wind/baseline | 1016 | 0 | 27 | 0 |

## Unsupported capabilities

* `facility_tax_attribution` — Facility-level deductible interest and tax allocation are not persisted (F3.8).
* `investor_specific_returns` — Investor-specific allocation is F4 scope and is not evidenced here.
* `npv` — Project and equity NPV are not published by the persisted Run (no persisted discount basis).
* `independent_project_irr` — The unlevered project cash-flow vector is not persisted, so Project IRR cannot be recomputed independently.
* `generation_times_price` — Generation is persisted only as display text and the price path is not persisted.
* `external_workbook_parity` — No authorised independent workbook reference is part of this repository.
