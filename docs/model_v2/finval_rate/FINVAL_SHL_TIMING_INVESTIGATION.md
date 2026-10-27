# FIN-VAL — SHL timing investigation (no engine correction)

Executed **78 direct, disposable, non-mutating cases**: both Solar and Wind; the full 8 construction-duration ×4 horizon matrix, three financial-close dates and four maturity/eligibility combinations per vertical. Raw inputs, outcomes, exact error text and KPIs for successful cases are in `evidence/shl-timing.json`.

| Vertical | Horizon years | 6 mo | 7 mo | 9 mo | 12 mo | 13 mo | 18 mo | 24 mo | 36 mo |
|---|---:|---|---|---|---|---|---|---|---|
| solar | 15 | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED |
| solar | 20 | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED |
| solar | 25 | REFUSED | REFUSED | REFUSED | REFUSED | OK | OK | OK | OK |
| solar | 30 | REFUSED | OK | OK | OK | OK | OK | OK | OK |
| wind | 15 | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED |
| wind | 20 | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED |
| wind | 25 | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED | REFUSED |
| wind | 30 | REFUSED | OK | OK | OK | OK | OK | OK | OK |

Solar: **15 feasible / 24 refused**. Wind: **11 feasible / 28 refused**. These totals include the date/SHL variants, not just the duration/horizon table. All failures are explicit exceptions, not silent numeric fallback.

## Root causes distinguished

- Absolute SHL maturity and eligibility indices are initialized at factory construction (`shl_maturity_period_index`, `shl_principal_eligibility_start_period`). Editing timeline info does not derive a new contractual SHL policy. A shorter operating horizon or fewer construction periods can leave those indices outside the canonical grid.
- Construction CAPEX events also have their own period authority; a reduced construction schedule can produce `H1_CAPEX_TIMING_EXCEEDS_CONSTRUCTION` before the SHL evaluation. That is a different failure from SHL maturity indexing.
- Date/stub boundaries alter the actual canonical axis; ceil(months/6) alone is insufficient to reconstruct every financing event.
- An on-grid maturity can still fail because the configured waterfall cannot settle SHL principal. The 9% rate matrix illustrates actual residual liabilities, which cannot be repaired by relabeling periods.
- An eligibility index after maturity is invalid even if both dates are otherwise on-grid.

The earlier audit's shorthand “build >=13 months / horizon25–30” is not a universally safe envelope: the independently executed Wind 25-year matrix refuses all eight construction choices. Do not promote that recommendation into a product promise.

## Separate governed design proposal

Represent policy as contractual events relative to financial close, COD, actual senior maturity and operating-horizon end, with explicit owner-approved inclusivity and stub-period rules. Derive event-to-period mapping from the single canonical PeriodEngine axis. Distinguish eligibility from maturity and separate funding draw dates from repayment entitlement. Validate construction CAPEX event coverage, tenor/operating-frequency alignment and full funding-period reconciliation before Run.

Preserve a source-calibrated absolute schedule when that is the explicit contractual authority; never silently rebase it. An owner-approved conversion must show old/new event dates, grid indices, funding sources/uses and every liability at contractual maturity. Reject unsupported or off-grid configurations rather than extending/forgiving a liability.

A future timing correction must be a separate Financial Owner-governed PR with unchanged golden protections and independent cash/interest/funding-period tests. This branch changes no SHL engine, timeline formula, solver or investor economics.
