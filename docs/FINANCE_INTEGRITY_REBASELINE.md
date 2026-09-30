# Finance Integrity stream — reference rebaseline

This document records every reference value that moved when the Finance Integrity
corrections (H-2, H-1, H-3, H-4b) landed, with the old value, the new value, the economic
reason and the correction responsible. No value was updated blindly: each one is explained
by a specific correction, and the tests that pin them were changed deliberately.

Scope: the four canonical references (Solar, Wind, Data Center, EV Charging). Storage is not
part of this rebaseline and is not promoted.

## Corrections in this stream

| Id | Correction | Effect on numbers |
|---|---|---|
| H-2 | DSCR sculpting feasibility: the backward pass can no longer leave a period whose debt service the cash flow cannot fund; an infeasible sizing returns the typed `DSCR_SCULPTING_INFEASIBLE` result instead of a false `CONVERGED`. | Data Center senior debt and minimum DSCR. |
| H-1 | Construction interest (IDC), commitment fee, structuring fee and an explicit sponsor-funded initial DSRA are applied to the product run through the existing typed construction-financing authority. Total Project Uses now include them, Sources = Uses with no plug, and gearing is measured on Total Project Uses. | Senior debt, gearing, derived shareholder loan, equity and sponsor returns. |
| H-3 | Share-capital IRR (equity only) and Total Sponsor XIRR (equity + shareholder loan) are labelled explicitly. Return maths and machine field meaning are unchanged. | Labels only. |
| H-4b | Run Integrity Checks are read from the committed Last Run evidence. | No numbers change. |

## Reference values

| Reference | Metric | Old | New | Economic reason | Correction |
|---|---|---|---|---|---|
| Solar | Senior debt (kEUR) | 24,750.00 | 26,983.33 | 75% gearing now applies to Total Project Uses 35,977.78 (33,000 CAPEX + IDC 544.71 + commitment fee 229.70 + structuring fee 269.83 + initial DSRA 1,933.53), not to CAPEX alone. | H-1 |
| Solar | Derived shareholder loan (kEUR) | 7,750 | 8,494.44 | Funds the larger Uses not covered by senior debt and 500 kEUR share capital. | H-1 |
| Solar | Project IRR | 11.557% | 11.768% | Financing costs and the DSRA stay outside the unlevered project return (recorded as excluded uses); the change is CAPEX timing, which now follows the typed semiannual construction periods (20,000 kEUR at 2030-06-30, 13,000 kEUR at 2030-12-31) instead of 14 equal monthly instalments. | H-1 |
| Solar | Share-capital IRR | 50.468% | 45.953% | Larger shareholder-loan share of funding and financing costs carried by sponsors. | H-1 |
| Solar | Total Sponsor XIRR | 17.896% | 16.610% | Same. | H-1 |
| Solar | Minimum DSCR | 1.2498x | 1.2486x | Larger debt at the same sculpting target. | H-1 |
| Solar | Average DSCR | 2.158x | 1.279x | The old mean was dominated by a 19.8x payoff period; the payoff period is now 1.35x. The mean is sensitive to where the final payoff lands (see limitations). | H-1 |
| Solar | First-period senior interest (kEUR) | 457.53 | 498.82 | 26,983.33 × 5.5% × 121/360 on the larger balance. | H-1 |
| Wind | Senior debt (kEUR) | 32,250.00 | 36,505.16 | 75% of Total Project Uses 48,673.54. | H-1 |
| Wind | Project IRR | 13.722% | 13.311% | CAPEX timing follows the typed construction periods; financing costs and the DSRA stay outside the unlevered return. | H-1 |
| Wind | Share-capital IRR | 74.595% | 68.422% | As Solar. | H-1 |
| Wind | Total Sponsor XIRR | 20.794% | 18.712% | As Solar. | H-1 |
| Wind | Minimum DSCR | 1.2826x | 1.2800x | Larger debt at the same target. | H-1 |
| EV Charging | Senior debt (kEUR) | 5,850.00 | 6,477.35 | 65% of Total Project Uses 9,965.16 (9,000 CAPEX + IDC 89.58 + commitment fee 53.28 + structuring fee 64.77 + initial DSRA 757.52). | H-1 |
| EV Charging | Derived shareholder loan (kEUR) | 2,650 (template) | 2,987.81 | Engine-derived residual: Sources = Uses with no plug. | H-1 |
| EV Charging | Project IRR | 14.679% | 15.086% | CAPEX timing follows the typed construction periods; financing costs and the DSRA stay outside the unlevered return. | H-1 |
| EV Charging | Share-capital IRR | 39.541% | 37.628% | As Solar. | H-1 |
| EV Charging | Total Sponsor XIRR | 20.373% | 18.722% | As Solar. | H-1 |
| EV Charging | Average DSCR | 1.362x | 7.838x | Gearing binds; the balance clears with a 9.8 kEUR payoff in the last debt period (DSCR 99x), which dominates a simple mean. Minimum DSCR is unchanged at 1.30x. | H-1 (see limitations) |
| Data Center | Senior debt (kEUR) | 80,436.50 | 58,410.96 | The former figure was a false `CONVERGED` state: its debt service in the occupancy ramp could not be funded from cash flow. The corrected sizing services every period at the 1.30x target. | H-2 |
| Data Center | Minimum DSCR | 0.944x | 1.300x | Same. The previous sub-1.0 figure was the defect, not an economic feature of the reference. | H-2 |
| Data Center | Gearing | 40.22% (on CAPEX) | 28.06% (on Total Project Uses 208,200.59) | Smaller correctly sized debt; larger Uses basis. | H-2 / H-1 |
| Data Center | Total Project Uses (kEUR) | 200,000 | 208,200.59 | CAPEX + IDC 1,003.56 + commitment fee 1,068.04 + structuring fee 584.11 + initial DSRA 5,544.88. | H-1 |
| Data Center | Share capital (kEUR) | 80,000 | 90,000 | Reference assumption — see below. | Flagged recalibration |
| Data Center | Derived shareholder loan (kEUR) | 39,563.50 | 59,789.63 | Smaller senior debt and larger Uses are funded by the shareholder loan. | H-2 / H-1 |
| Data Center | Project IRR | 2.293% | 2.301% | CAPEX timing follows the typed construction periods; financing costs and the DSRA stay outside the unlevered return. | H-1 |
| Data Center | Share-capital IRR | not available | −4.883% | Computable now that the sizing is consistent. | H-2 |
| Data Center | Total Sponsor XIRR | not available | 2.079% | Same. | H-2 |

## Items that need reviewer approval

1. **Data Center reference share capital 80,000 → 90,000 kEUR** (`DC_SHARE_CAPITAL_KEUR_PER_MW`
   4,000 → 4,500). With H-2 and H-1 both applied, the shareholder loan derived at 80,000 kEUR
   cannot be repaid from post-senior cash by its maturity, and the run fails closed with
   `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` (about 15.5 MEUR left at maturity). No maturity was
   extended, no repayment was invented and the shareholder loan was not removed. The reference
   is a synthetic demonstration input, so its declared equity was raised until it is feasible
   (it runs at 90,000 and fails closed at 80,000). The alternative is to leave the reference
   failing closed. This is an assumption change, not a maths change, and needs approval.
   Low-occupancy sensitivities of the Data Center reference fail closed for the same reason,
   which is the intended typed behaviour.
2. **Governance contract for frozen-engine guards.** The blanket "financial_engine has zero
   diff from main" tests were replaced by an allow-list
   (`tests/finance_integrity_governance.py`): only the nine engine files this stream changes may
   differ from main; every other engine module, `finco_core/**` and `finco_radar/**` stay
   strictly frozen.

## Known limitations

- **Run time.** A product run now takes about 18 s (was about 1 s): the construction-financing
  and DSRA fixed points call the senior, shareholder-loan and tax solvers many times. Identical
  repeat runs in one process are memoised. Application start-up seeds the reference Last Runs
  and now takes roughly a minute or more on a cold database; browser test fixtures were given
  matching start-up deadlines. A performance change to the engine loops is outside this stream.
- **Average DSCR** is a simple mean and is distorted by a small payoff period (EV Charging).
  Minimum DSCR and the per-period schedule are the meaningful measures.
- **Zero-shareholder-loan statements.** A pure-equity project (no shareholder loan) still fails
  in financial statements assembly. This is pre-existing; the returns are tested at the
  shareholder-waterfall level.
- **Initial DSRA policy.** The generic product policy funds the initial DSRA from sponsors
  through the construction financing waterfall, sized at the peak forward senior debt service
  over `dsra_months`, and releases it under the existing DSRA release rules.
