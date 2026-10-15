# WF-A credit validation matrix

A successful stress Run is not a validation PASS, and a credit identity PASS does not establish bankability. Directional expectations follow the product's actual sizing mechanics.

Metric rows: {'PASS': 30, 'FAIL': 0, 'UNAVAILABLE': 0, 'NOT_COMPARABLE': 0}  ·  Directional checks: {'PASS': 14, 'FAIL': 0, 'UNAVAILABLE': 0, 'NOT_ASSERTED': 1}

## Reported vs independently recomputed

| Case | Run | Assumption delta | Metric | Reported | Independent | Signed difference | Allowance | Result |
|---|---|---|---|---|---|---|---|---|
| wind-R0 | `20104d1d` | baseline, DSCR-sized, P50 lender case | Senior debt quantum (solver final size vs Sources & Uses) | 12238.919461 | 12238.919461 | 0.000000000000 | 0.000001 | PASS |
| wind-R0 | `20104d1d` | baseline, DSCR-sized, P50 lender case | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.00 | 0.000000 | PASS |
| wind-R0 | `20104d1d` | baseline, DSCR-sized, P50 lender case | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | 0.000000 | 0.000000 | PASS |
| wind-R0 | `20104d1d` | baseline, DSCR-sized, P50 lender case | Average DSCR (reported vs recomputed) | 1.359514 | 1.359514 | -0.000000 | 0.000000 | PASS |
| wind-R0 | `20104d1d` | baseline, DSCR-sized, P50 lender case | Total Senior debt service (reported vs scheduled sum) | 15542.973195 | 15542.973195 | 0.000000 | 0.000001 | PASS |
| wind-R0 | `20104d1d` | baseline, DSCR-sized, P50 lender case | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| wind-R-hours-30 | `e1b635e1` | P50 generation hours -30% | Senior debt quantum (solver final size vs Sources & Uses) | 12023.285309 | 12023.285309 | 0.000000000000 | 0.000001 | PASS |
| wind-R-hours-30 | `e1b635e1` | P50 generation hours -30% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| wind-R-hours-30 | `e1b635e1` | P50 generation hours -30% | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| wind-R-hours-30 | `e1b635e1` | P50 generation hours -30% | Average DSCR (reported vs recomputed) | 2.099051 | 2.099051 | -0.000000 | 0.000000 | PASS |
| wind-R-hours-30 | `e1b635e1` | P50 generation hours -30% | Total Senior debt service (reported vs scheduled sum) | 16870.906486 | 16870.906486 | -0.000000 | 0.000001 | PASS |
| wind-R-hours-30 | `e1b635e1` | P50 generation hours -30% | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| wind-F0 | `68594090` | baseline, GEARING_CAP (debt sized on cost) | Senior debt quantum (solver final size vs Sources & Uses) | 11953.392579 | 11953.392579 | 0.000000000000 | 0.000001 | PASS |
| wind-F0 | `68594090` | baseline, GEARING_CAP (debt sized on cost) | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| wind-F0 | `68594090` | baseline, GEARING_CAP (debt sized on cost) | Minimum DSCR (reported vs recomputed) | 1.145445 | 1.145445 | -0.000000 | 0.000000 | PASS |
| wind-F0 | `68594090` | baseline, GEARING_CAP (debt sized on cost) | Average DSCR (reported vs recomputed) | 2.154033 | 2.154033 | 0.000000 | 0.000000 | PASS |
| wind-F0 | `68594090` | baseline, GEARING_CAP (debt sized on cost) | Total Senior debt service (reported vs scheduled sum) | 17009.749582 | 17009.749582 | 0.000000 | 0.000001 | PASS |
| wind-F0 | `68594090` | baseline, GEARING_CAP (debt sized on cost) | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| wind-F-hours-30 | `e7007e91` | P50 generation hours -30% | Senior debt quantum (solver final size vs Sources & Uses) | 11953.392579 | 11953.392579 | 0.000000000000 | 0.000001 | PASS |
| wind-F-hours-30 | `e7007e91` | P50 generation hours -30% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| wind-F-hours-30 | `e7007e91` | P50 generation hours -30% | Minimum DSCR (reported vs recomputed) | 0.825122 | 0.825122 | 0.000000 | 0.000000 | PASS |
| wind-F-hours-30 | `e7007e91` | P50 generation hours -30% | Average DSCR (reported vs recomputed) | 1.546835 | 1.546835 | 0.000000 | 0.000000 | PASS |
| wind-F-hours-30 | `e7007e91` | P50 generation hours -30% | Total Senior debt service (reported vs scheduled sum) | 17009.749582 | 17009.749582 | 0.000000 | 0.000001 | PASS |
| wind-F-hours-30 | `e7007e91` | P50 generation hours -30% | Periods in lock-up (reported vs closed-gate periods) | 2 | 2 | 0 | 0.000000 | PASS |
| wind-L-P90 | `345f1c18` | P90-10y lender case vs P50 | Senior debt quantum (solver final size vs Sources & Uses) | 12168.385986 | 12168.385986 | 0.000000000000 | 0.000001 | PASS |
| wind-L-P90 | `345f1c18` | P90-10y lender case vs P50 | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| wind-L-P90 | `345f1c18` | P90-10y lender case vs P50 | Minimum DSCR (reported vs recomputed) | 1.280550 | 1.280550 | 0.000000 | 0.000000 | PASS |
| wind-L-P90 | `345f1c18` | P90-10y lender case vs P50 | Average DSCR (reported vs recomputed) | 1.520772 | 1.520772 | 0.000000 | 0.000000 | PASS |
| wind-L-P90 | `345f1c18` | P90-10y lender case vs P50 | Total Senior debt service (reported vs scheduled sum) | 15846.619283 | 15846.619283 | -0.000000 | 0.000001 | PASS |
| wind-L-P90 | `345f1c18` | P90-10y lender case vs P50 | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |

## Directional checks

| Check | Expectation | From → To | Values | Result |
|---|---|---|---|---|
| wind: fixed debt unchanged under hours-30 | debt quantum unchanged | F0 → F-hours-30 | 11953.392579 → 11953.392579 | PASS |
| wind: fixed debt service unchanged under hours-30 | total Senior service unchanged | F0 → F-hours-30 | 17009.749582 → 17009.749582 | PASS |
| wind: fixed minimum DSCR under hours-30 | minimum DSCR falls | F0 → F-hours-30 | 1.145445 → 0.825122 | PASS |
| wind: fixed lock-up periods under hours-30 | lock-up periods do not fall | F0 → F-hours-30 | 0 → 2 | PASS |
| wind: fixed EBITDA under hours-30 | EBITDA falls | F0 → F-hours-30 | 87748.040528 → 59489.046645 | PASS |
| wind: resized debt shrinks under hours-30 | re-sized debt quantum falls | R0 → R-hours-30 | 12238.919461 → 12023.285309 | PASS |
| wind: resized EBITDA under hours-30 | EBITDA falls | R0 → R-hours-30 | 87748.040528 → 59489.046645 | PASS |
| wind: resized hours-30: debt direction | not asserted: the gearing cap binds | R0 → R-hours-30 | 12238.919461 → 12023.285309 | NOT_ASSERTED |
| wind: R-hours-30: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → R-hours-30 | 0 → -0.000000 | PASS |
| wind: L-P90: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → L-P90 | 0 → 0.000000 | PASS |
| wind: R0 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R0 | 1.200000 → 1.200000 | PASS |
| wind: R-hours-30 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-hours-30 | 1.200000 → 1.200000 | PASS |
| wind: P90 lender case does not enlarge debt | P90 debt quantum is not above P50 | R0 → L-P90 | 12238.919461 → 12168.385986 | PASS |
| wind: lender case leaves the operating case unchanged | EBITDA identical under P50 and P90 lender cases | R0 → L-P90 | 87748.040528 → 87748.040528 | PASS |
| wind: P90 keeps base coverage at or above P50 | base minimum DSCR not below P50 case | R0 → L-P90 | 1.200000 → 1.280550 | PASS |
