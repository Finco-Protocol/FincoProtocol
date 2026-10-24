# WF-09A — isolated LCOE / LCOS candidate, release CLOSED

Source inspected: main 93c549e160772acd8258c26556bd46ff9ca29156,
tree 920c899b3e769fededcfc45253c8cc51b1a6f095 (2026-10-24).
No owner policy is approved here. No product import, route, Run output, certificate,
feature flag, financial source or protected pin is changed. The new arithmetic is
under research/wf09a, deliberately outside production analytics exports.

## Current-source inventory and authority

| Source | Observed behavior / origin | Status for this proposal |
|---|---|---|
| app/model_v2/canonical_analytics.py, _LCOE_AUTHORITY_NOTE and _future_metric | Explicitly declares no canonical LCOE authority; no production caller for orphan helper | Production metric remains FUTURE/unavailable |
| domain/analytics/lcoe.py | CAPEX at Y0; OPEX Y1..N inflated from Y1; energy discounted at same year ends, degradation exponent starts at year 1 | Frozen legacy extra, not adopted as financial authority |
| domain/analytics/scenarios.py, _compute_lcoe_from_waterfall | Undiscounted CAPEX + operating OPEX divided by lifetime MWh, with factor 1000 | Private presentation variant, not equivalent to discounted LCOE |
| financial_engine/orchestrator.py | Canonical operating periods; generation, revenue and OPEX schedules; BESS expense receipt integration | Future adapter must consume existing receipts, not recompute leaves |
| domain/capex/capex_schedule.py; domain/capex/spending_profile.py | Construction-period spending distribution | Use exact canonical cash dates and approved profile; no Y0 collapse |
| domain/opex/runtime_adapter.py | Narrow hierarchical adapter limited to REF-WIND-B | Not a universal project OPEX authority; use canonical run schedules |
| financial_engine/tax/engine.py | Canonical cash-tax results | Consume actual cash tax; depreciation is not a second cash cost |
| financial_engine/financial_statements/assembly.py | Downstream date-joined statements, construction funding, cash identities; rejects mismatched axes | Reconcile source schedules before costing; bank CFADS differs from post-senior cash |
| financial_engine/valuation/model.py | Typed dated discounting, rate/timing conventions, project NPV and lender coverage | Separate approved valuation policies; no implicit reuse as LCOE policy |
| financial_engine/bess.py | Native hourly settlement receipts: gross sale, charging/auxiliary buys, import/export charges, variable O&M, grid MWh, SOH/EFC | Actual native contract required; legacy flag is rejected; events raise BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED; nonzero initial/terminal inventory basis rejected |
| domain/revenue/bess.py | Legacy discharge approximation uses RTE, annual degradation and spread; augmentation linear allocation | Observational legacy source, not native LCOS authority |
| domain/bess/dispatch.py; domain/bess/settlement.py | Native physical/settlement evidence consumed by financial_engine/bess.py | Future denominator must name physical boundary and use actual receipts |

Legacy issues observed, deliberately NOT corrected: lcoe.py divides kEUR by MWh
without multiplying by 1000 while labelling EUR/MWh; its component helper references
nonexistent result.pv_total and mixes undiscounted OPEX with discounted totals.
The scenarios variant applies the numerical factor 1000, but its explanatory
kEUR/GWh unit statement is incorrect. No accepted legacy output is changed.

Historical REFERENCE_HARVEST_V4_DELTA_PRIVATE.zip was not available in this workspace.
User-supplied Solar attribution 2.10 + 61.74 + 19.06 + 10.21 + 5.77 = 98.88 $/MWh
is an observation only, not independently authenticated policy or a numerical golden.
USD figures cannot be compared directly with this candidate's EUR results.

## Proposed definitions — decisions PENDING Financial Owner

For exact dated rows t, explicitly supplied positive discount factors d(t), signed
costs C_i(t) in kEUR and delivered E(t) in MWh:

PV_i = sum_t d(t)*C_i(t); PV_E = sum_t d(t)*E(t).
Candidate EUR/MWh = 1000*sum_i PV_i/PV_E. Each component uses the same PV_E.
PV_E <= 0 or missing convention/rate provenance means UNAVAILABLE, never a zero price.
An explicitly evidenced zero cost with positive energy is a legitimate zero.
Negative costs (refunds/credits) retain their sign; energy cannot be negative.

1. Unlevered pre-financing/pre-tax: DEVEX + CAPEX + OPEX; finance and tax explicitly
zero with provenance. No loan proceeds, debt principal repayment or equity funding
in cost. DEVEX capitalized into CAPEX must be removed from one component.
2. Levered after-tax project cost: five disjoint DEVEX/CAPEX/OPEX/finance/tax buckets.
Finance convention must decide interest/fees/IDC timing and capitalized IDC removal
from CAPEX. This is not automatically an equity-required-price metric: principal
and distributions cannot be added to already financed capital expenditure. Tax
must distinguish cash paid/refunds from accounting tax and specify deductibility.
No endogenous tax-on-required-price solve is implemented.
3. LCOS: same disjoint buckets with explicit paid charging electricity included
once within OPEX; exported/delivered AC discharge MWh denominator. Charging must
include relevant buy prices, import tariffs and auxiliary consumption at the
approved boundary. A net arbitrage spread alone cannot recover a gross charging
cost; candidate returns UNAVAILABLE for net-spread LCOS. Revenue is not subtracted
as if it were a charging expense.

Financial Owner decisions required: valuation date, beginning/end/mid-period or
actual dates; annual/monthly/quarterly day-count and stub handling; real/nominal
cost/rate pairing; rate source and pre-/after-tax debt/equity/WACC interpretation;
currency/FX date; taxes/refunds and terminal proceeds; construction DEVEX/CAPEX/IDC
boundary; charging tariffs, energy boundary and inventory accounting. Each requires
an authentic independent decision reference before product connection.

Different rates, tax bases, energy boundaries, construction dates, inflation,
financing conventions or currency make the metrics non-comparable. Annual sums
cannot replace dated discounted cashflows: aggregate discounted amounts and energy,
or retain each factor. Standalone tests split same-factor rows only; no implicit
annual-to-quarterly rate conversion is introduced.

## Pure candidate contract and limitations

Frozen typed records use Decimal inputs, immutable tuples, explicit period IDs,
five components and unique source line identities including explicit zeros. Reusing
an origin across finance/tax/charging/any bucket or period is rejected. Inputs must
already be atomized by a future reviewed adapter; fabricated distinct IDs cannot
prove economic disjointness. Supplied convention text is a receipt, not approval.
The caller supplies aligned discount factors, so rate derivation is deliberately
not implemented. Arithmetic runs at fixed 50-digit Decimal precision; quotient
components may have final-digit division rounding, while PV numerators reconcile
exactly within that precision. No display rounding or published production figure
is created. Every result is CANDIDATE or UNAVAILABLE, never APPROVED.

## BESS Commercial WF-08 connection — future only

Do not infer WF-08 approval from native technical capability. A later independently
reviewed adapter must supply paid charging and delivered energy from native receipts,
with RTE losses reflected in actual import/export energy exactly once. Confirm
cycle/calendar degradation and SOH affect actual dispatch, not a second generic
energy haircut. Augmentation requires an approved financial posting/lifecycle basis
(current native event posting is release-closed); no legacy linear allowance is
substituted. Resolve inventory, residual values, replacement CAPEX, variable O&M
throughput basis, grid fees, cash tax and financing receipts. Reconcile every row
against canonical statements and provenance/certificates without altering them.
Missing inputs remain UNAVAILABLE. Only after policy sign-off, independent review
and later product acceptance may a separate integration expose any metric.

## Preservation and evidence

No existing file is modified. Protected financing/project.py, shareholder waterfall,
native kernels, owner records and every existing test remain byte-identical to main.
React Epic, #357 and #358 are untouched. Live PR inventory found no open WF09A cost
library PR; performance workstreams #318/#321/#322/#324/#327/#328 are not incorporated.
See the Draft PR for its exact commit and automatic CI; earlier-head CI is not proof.
