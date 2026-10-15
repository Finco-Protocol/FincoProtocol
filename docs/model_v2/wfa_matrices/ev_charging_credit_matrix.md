# WF-A credit validation matrix

A successful stress Run is not a validation PASS, and a credit identity PASS does not establish bankability. Directional expectations follow the product's actual sizing mechanics.

Metric rows: {'PASS': 18, 'FAIL': 0, 'UNAVAILABLE': 0, 'NOT_COMPARABLE': 0}  ·  Directional checks: {'PASS': 3, 'FAIL': 0, 'UNAVAILABLE': 6, 'NOT_ASSERTED': 0}

## Reported vs independently recomputed

| Case | Run | Assumption delta | Metric | Reported | Independent | Signed difference | Allowance | Result |
|---|---|---|---|---|---|---|---|---|
| ev_charging-R0 | `69687960` | baseline, DSCR-sized | Senior debt quantum (solver final size vs Sources & Uses) | 20727.528253 | 20727.528253 | 0.00000000000 | 0.000001 | PASS |
| ev_charging-R0 | `69687960` | baseline, DSCR-sized | Gearing (recorded vs Senior / total uses) | 0.650000 | 0.650000 | -0.000000 | 0.000000 | PASS |
| ev_charging-R0 | `69687960` | baseline, DSCR-sized | Minimum DSCR (reported vs recomputed) | 1.300000 | 1.300000 | -0.000000 | 0.000000 | PASS |
| ev_charging-R0 | `69687960` | baseline, DSCR-sized | Average DSCR (reported vs recomputed) | 1.306155 | 1.306155 | 0.000000 | 0.000000 | PASS |
| ev_charging-R0 | `69687960` | baseline, DSCR-sized | Total Senior debt service (reported vs scheduled sum) | 26319.045056 | 26319.045056 | -0.000000 | 0.000001 | PASS |
| ev_charging-R0 | `69687960` | baseline, DSCR-sized | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| ev_charging-F0 | `4db5b7f0` | baseline, GEARING_CAP (debt sized on cost) | Senior debt quantum (solver final size vs Sources & Uses) | 20187.668806 | 20187.668806 | 0.00000000000 | 0.000001 | PASS |
| ev_charging-F0 | `4db5b7f0` | baseline, GEARING_CAP (debt sized on cost) | Gearing (recorded vs Senior / total uses) | 0.650000 | 0.650000 | -0.000000 | 0.000000 | PASS |
| ev_charging-F0 | `4db5b7f0` | baseline, GEARING_CAP (debt sized on cost) | Minimum DSCR (reported vs recomputed) | 0.662288 | 0.662288 | 0.000000 | 0.000000 | PASS |
| ev_charging-F0 | `4db5b7f0` | baseline, GEARING_CAP (debt sized on cost) | Average DSCR (reported vs recomputed) | 1.996352 | 1.996352 | 0.000000 | 0.000000 | PASS |
| ev_charging-F0 | `4db5b7f0` | baseline, GEARING_CAP (debt sized on cost) | Total Senior debt service (reported vs scheduled sum) | 26634.264378 | 26634.264378 | 0.000000 | 0.000001 | PASS |
| ev_charging-F0 | `4db5b7f0` | baseline, GEARING_CAP (debt sized on cost) | Periods in lock-up (reported vs closed-gate periods) | 4 | 4 | 0 | 0.000000 | PASS |
| ev_charging-R-capex+10 | `6acc0fd6` | CAPEX contingency +10% | Senior debt quantum (solver final size vs Sources & Uses) | 21477.558843 | 21477.558843 | 0.00000000000 | 0.000001 | PASS |
| ev_charging-R-capex+10 | `6acc0fd6` | CAPEX contingency +10% | Gearing (recorded vs Senior / total uses) | 0.650000 | 0.650000 | -0.000000 | 0.000000 | PASS |
| ev_charging-R-capex+10 | `6acc0fd6` | CAPEX contingency +10% | Minimum DSCR (reported vs recomputed) | 1.300000 | 1.300000 | 0.000000 | 0.000000 | PASS |
| ev_charging-R-capex+10 | `6acc0fd6` | CAPEX contingency +10% | Average DSCR (reported vs recomputed) | 1.528823 | 1.528823 | 0.000000 | 0.000000 | PASS |
| ev_charging-R-capex+10 | `6acc0fd6` | CAPEX contingency +10% | Total Senior debt service (reported vs scheduled sum) | 27437.212767 | 27437.212767 | 0.000000 | 0.000001 | PASS |
| ev_charging-R-capex+10 | `6acc0fd6` | CAPEX contingency +10% | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |

## Directional checks

| Check | Expectation | From → To | Values | Result |
|---|---|---|---|---|
| ev_charging: fixed debt unchanged under opex+50 | debt quantum unchanged | F0 → F-opex+50 | 20187.668806 → — | UNAVAILABLE |
| ev_charging: fixed debt service unchanged under opex+50 | total Senior service unchanged | F0 → F-opex+50 | 26634.264378 → — | UNAVAILABLE |
| ev_charging: fixed minimum DSCR under opex+50 | minimum DSCR falls | F0 → F-opex+50 | 0.662288 → — | UNAVAILABLE |
| ev_charging: fixed lock-up periods under opex+50 | lock-up periods do not fall | F0 → F-opex+50 | 4 → — | UNAVAILABLE |
| ev_charging: fixed EBITDA under opex+50 | EBITDA falls | F0 → F-opex+50 | 131843.677204 → — | UNAVAILABLE |
| ev_charging: resized capex+10 raises uses and equity | equity funding rises | R0 → R-capex+10 | 11160.976751 → 11564.839377 | PASS |
| ev_charging: resized opex+50 lowers EBITDA | EBITDA falls | R0 → R-opex+50 | 131843.677204 → — | UNAVAILABLE |
| ev_charging: R0 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R0 | 1.300000 → 1.300000 | PASS |
| ev_charging: R-capex+10 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-capex+10 | 1.300000 → 1.300000 | PASS |

## Cases without a committed Run

* `ev_charging-R-opex+50` — OPEX contingency +50%: The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
* `ev_charging-F-opex+50` — OPEX contingency +50%: The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
