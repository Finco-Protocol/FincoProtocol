# WF-08A — BESS Commercial & Lender Contract Candidate: Financial Owner Decision Packet

Candidate: `app/bess_commercial_candidate/` (RELEASE-CLOSED; `ACTIVATION_ENABLED` is a literal `False`).
Every decision below is **OPEN**. No candidate behaviour is financial authority. Where the code must do *something* to stay
safe, it takes the most conservative option (fail closed or UNAVAILABLE) and says so; that is a safety default, not a policy.
The code cannot record any of these decisions as anything but `OPEN` (`Decision` has no other member).

Not covered here: Revenue V4 negative-price policy and PPA-01 — see B-10 for the interaction only.

## B-01 — Charging accounting conventions

Native receipts split purchases into `charging_purchase_cost` (charge MW × buy price) and `auxiliary_purchase_cost`
(grid-fed auxiliary MW × buy price), plus import/export charges on gross grid energy. Owner decides: are auxiliary purchases
part of "charging cost" for lender and LCOS presentation; are import/export charges energy cost or a separate network cost;
which party's price (buy price vs a settlement-point price) applies; refunds/credits (the candidate accepts non-negative
amounts only and rejects negative receipts).
*Candidate behaviour:* each leg is reported separately; `gross_charging_cost` = charging + auxiliary, labelled as such.

## B-02 — Net spread vs explicit energy purchases

NET_SPREAD says the quoted price already is a net arbitrage spread and the gross purchase is unknown; EXPLICIT_BUY_LEG uses
independently reported gross sale and purchase receipts. Owner decides: which basis is admissible for which contract type and
lender case; whether a net-spread product may ever be shown beside an explicit buy-leg product; and the evidence required to
claim a basis.
*Candidate behaviour:* the two bases cannot be mixed in a period or reconstructed from each other; a NET_SPREAD period never
yields a charging cost, and LCOS receipts for it are UNAVAILABLE.

## B-03 — Tolling capacity and energy ownership

The candidate records `contracted_capacity_mw`, `energy_ownership` and `dispatch_responsibility` as declared parties.
Owner decides the **allocation** of: merchant upside outside the toll; availability penalties; **who bears charging cost**;
**who bears degradation / SoH risk**. These are four fields fixed at OPEN.
*Candidate behaviour:* none of the four is computed; the fee schedule and declared deductions are reported only.

Related sub-decisions: the day-count convention (only `ACT_365_FIXED` is implemented, so any other fails closed); the
availability **penalty formula** linking a shortfall to a deduction (deductions are DECLARED amounts with evidence; the code
rejects a deduction without a declared guarantee or without a shortfall, and rejects deductions above the scheduled fee);
treatment of a negative net fee; whether the availability fee scales with measured availability or is flat with deductions.

## B-04 — Revenue classification definitions

`CONTRACTED`, `CONTRACTED_UNSECURED` and `MERCHANT` are *declared* by the caller; the code only enforces that contracted
classes carry a `contract_ref` and merchant revenue does not. Owner decides what makes a contract "secured" (counterparty
credit, guarantee, tenor, termination rights) and who classifies.

## B-05 — Contracted vs merchant lender treatment

The candidate presents three SEPARATE categories per period and never nets them; `CONTRACTED_UNSECURED` is its own category
and is never merged into `CONTRACTED`. Owner decides how each category enters a lender cash flow (CFADS) and sizing.
*Candidate behaviour:* presentation only; the released CFADS, debt-sizing and DSCR engines are not touched.

## B-06 — DSCR eligibility and haircut policies

Per class: is it DSCR-eligible; in what proportion (haircut); for what tenor; how a mixed stack is sized. All OPEN
(`dscr_eligibility`, `haircut` are `Decision.OPEN` for every class). The candidate applies no haircut or discount.

## B-07 — Dispatch allocation boundaries

Throughput-based services (`ENERGY_THROUGHPUT`, `MERCHANT_ENERGY`) claim physical AC MWh; reservation services
(`CAPACITY_RESERVATION`, `ANCILLARY_AVAILABILITY`) claim MW over a window and consume **no** throughput by themselves. Owner decides:
whether one MW may back several services at once (the candidate **rejects** over-reservation of the rated power as the
conservative default); how ancillary activation energy is treated and settled; priority between a reservation and an energy
dispatch in the same hour; how unallocated native MWh is treated (the candidate reports it, it does not assign it).

## B-08 — Augmentation trigger and warranty treatment

The candidate records SOH-threshold, planned-event and warranty triggers, reading the native state of health. Owner decides the
trigger authority (who may trigger), whether a warranty event is a cost to the project or a recovery, the remedy
(`warranty_remedy`), and how a replacement CAPEX proposal is approved. No posting exists: native
`BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED` stays in force and the candidate's posting function is unconditionally closed.

## B-09 — Construction vs operating CAPEX; funding and residual value

`capex_classification`, `funding_treatment` and `residual_value_treatment` are OPEN. Owner decides whether augmentation CAPEX is
construction-period or operating-period CAPEX, how it is funded (equity, debt, reserve account), depreciation and tax book
treatment (native keeps `tax_book_policy = UNRESOLVED`), and the residual value of the replaced cohort. The candidate invents no
depreciation, financing, tax or cash-flow value.

## B-10 — LCOS receipt and denominator conventions; interaction with Revenue V4 negative-price settlement

LCOS (PR #362) is arithmetic only; this candidate specifies receipts: gross charging purchase, auxiliary purchase, grid-fee
receipts, delivered AC discharge MWh, operating cost, optional augmentation investment, methodology reference, evidence identities.
Owner decides the denominator (delivered AC discharge vs DC throughput vs another boundary), inventory/residual treatment, which
costs belong in the numerator, and the methodology reference to cite. Missing methodology or any missing receipt is UNAVAILABLE.

Interaction with Revenue V4: the native BESS engine requires non-negative prices, and Revenue V4's negative-price policies
(`SETTLE_NORMALLY`, `NO_SETTLEMENT`, `CURTAIL`) are candidate-only and release-closed. Owner decides whether a storage asset
may be *paid to charge* at a negative price, how that interacts with a negative-price policy on the discharge side, and how
negative prices enter the net-spread and explicit-buy-leg bases. Nothing is connected: the candidate rejects negative amounts.

## Required approvals for ANY release path

1. A Financial Owner exact-content decision for each decision above that the released slice depends on.
2. Independent review of every byte that would leave this package.
3. A reviewed adapter slice (revenue, financing and/or LCOS) with its own governance pins; the released CFADS/DSCR engines and
   native BESS sources stay untouched until then.
4. Until then the package stays release-closed and product users never see it.
