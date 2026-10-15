# WF-A credit validation matrix

A successful stress Run is not a validation PASS, and a credit identity PASS does not establish bankability. Directional expectations follow the product's actual sizing mechanics.

Metric rows: {'PASS': 6, 'FAIL': 0, 'UNAVAILABLE': 0, 'NOT_COMPARABLE': 0}  ·  Directional checks: {'PASS': 1, 'FAIL': 0, 'UNAVAILABLE': 7, 'NOT_ASSERTED': 0}

## Reported vs independently recomputed

| Case | Run | Assumption delta | Metric | Reported | Independent | Signed difference | Allowance | Result |
|---|---|---|---|---|---|---|---|---|
| data_center-R0 | `932c9975` | baseline, DSCR-sized | Senior debt quantum (solver final size vs Sources & Uses) | 46728.769436 | 46728.769436 | 0.00000000000 | 0.000001 | PASS |
| data_center-R0 | `932c9975` | baseline, DSCR-sized | Gearing (recorded vs Senior / total uses) | 0.280551 | 0.280551 | 0.000000 | 0.000000 | PASS |
| data_center-R0 | `932c9975` | baseline, DSCR-sized | Minimum DSCR (reported vs recomputed) | 1.300000 | 1.300000 | -0.000000 | 0.000000 | PASS |
| data_center-R0 | `932c9975` | baseline, DSCR-sized | Average DSCR (reported vs recomputed) | 1.308760 | 1.308760 | 0.000000 | 0.000000 | PASS |
| data_center-R0 | `932c9975` | baseline, DSCR-sized | Total Senior debt service (reported vs scheduled sum) | 62490.332876 | 62490.332876 | -0.000000 | 0.000001 | PASS |
| data_center-R0 | `932c9975` | baseline, DSCR-sized | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |

## Directional checks

| Check | Expectation | From → To | Values | Result |
|---|---|---|---|---|
| data_center: fixed debt unchanged under opex+50 | debt quantum unchanged | F0 → F-opex+50 | — → — | UNAVAILABLE |
| data_center: fixed debt service unchanged under opex+50 | total Senior service unchanged | F0 → F-opex+50 | — → — | UNAVAILABLE |
| data_center: fixed minimum DSCR under opex+50 | minimum DSCR falls | F0 → F-opex+50 | — → — | UNAVAILABLE |
| data_center: fixed lock-up periods under opex+50 | lock-up periods do not fall | F0 → F-opex+50 | — → — | UNAVAILABLE |
| data_center: fixed EBITDA under opex+50 | EBITDA falls | F0 → F-opex+50 | — → — | UNAVAILABLE |
| data_center: resized capex+10 raises uses and equity | equity funding rises | R0 → R-capex+10 | 119831.703122 → — | UNAVAILABLE |
| data_center: resized opex+50 lowers EBITDA | EBITDA falls | R0 → R-opex+50 | 232525.385696 → — | UNAVAILABLE |
| data_center: R0 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R0 | 1.300000 → 1.300000 | PASS |

## Cases without a committed Run

* `data_center-F0` — baseline, GEARING_CAP (debt sized on cost): The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
* `data_center-R-capex+10` — CAPEX contingency +10%: These inputs leave part of the shareholder loan unpaid at its maturity, so the model did not produce a result. Review OPEX, CAPEX, revenue or shareholder-loan terms and run again. Your edits are saved; the previous Last Run is unchanged.
* `data_center-R-opex+50` — OPEX contingency +50%: The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
* `data_center-F-opex+50` — OPEX contingency +50%: The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
