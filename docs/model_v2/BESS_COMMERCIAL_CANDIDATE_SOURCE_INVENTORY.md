# WF-08A — BESS Commercial & Lender Contract Candidate: Source Inventory (RELEASE-CLOSED)

Inspected on `main` `b72942f22f1d3a8dcce351b56b96fdba0e6b9cdd`, tree `ab9b84aecd342bba7fe072a10842de3b74f7ab1c` (2026-10-24; the
brief named `0397d9af…`, which main has since moved past by the merge of PR #363).
Companion: `BESS_COMMERCIAL_CANDIDATE_OWNER_DECISION_PACKET.md`. Nothing here approves a financial policy.

Open PR inventory at preflight found no existing BESS commercial / tolling / lender-contract PR. #364 (React main
integration) and the performance PRs (#318, #321, #322, #324, #327, #328) are not touched or incorporated. PR #363 (Revenue V4)
and #362 (WF-09A) are merged and unchanged.

## 1. Existing functionality identified BEFORE implementing anything new

| Existing source | What already exists | Role for this candidate |
|---|---|---|
| `domain/bess/contracts.py` | Immutable native configuration (`Battery`, `DispatchPoint`, `Augmentation`), exact-hour UTC timeline, bounded JSON, non-negative prices, RTE = charge × discharge efficiency, `tax_book_policy` forced to `UNRESOLVED`. | Read-only reference. Unit and policy source of truth. |
| `domain/bess/dispatch.py` | One hourly DC inventory equation: SoC window, charge/discharge efficiency, auxiliaries, grid limits, additive calendar + cycle degradation, cohort pool, outages, augment/replace events, energy-conservation residual, explicit terminal inventory; `HourEvidence` per hour in MWh / kEUR. | **Consumed** (hourly evidence: `ac_charge_mwh`, `ac_discharge_mwh`, `grid_*_mwh`, `soh_closing`, receipts). Never recomputed. |
| `domain/bess/settlement.py` | `FinancialPeriodProposal`: per canonical period gross sale, charging purchase, auxiliary purchase, import/export charges, net merchant contribution, lifecycle CAPEX proposal, reconciliation to the dispatch totals. Explicitly "proposals, never netted revenue or a second finance engine". | **Consumed** as the EXPLICIT_BUY_LEG receipt source. |
| `financial_engine/bess.py` | Native evidence into the one financial engine. Rejects any configuration `events` (`BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED`), non-zero initial/terminal inventory (`BESS_INVENTORY_FINANCIAL_BASIS_UNRESOLVED`), the legacy flag (`BESS_NATIVE_CONTRACT_REQUIRED`) and duplicate revenue authority. Variable O&M per DC MWh. | **Unchanged.** Augmentation posting stays closed; asserted in the tests. |
| `finco_core/inputs/bess_native.py` | Native input contract: configuration + `variable_om_eur_per_dc_mwh`. | Reference only. |
| `domain/revenue/bess.py` | Legacy approximation: `arbitrage_spread_eur_mwh × discharged MWh` (a NET spread), annual `capacity_revenue_eur_mw_year`, `ancillary_revenue_eur_mw_year`, linear 10-year augmentation allocation, availability and annual degradation factors. | **Not reused** as native receipts. It is the origin of the "net spread" notion; its outputs are pinned unchanged. |
| `research/wf09a/costing.py` (PR #362) | Isolated frozen-Decimal cost attribution; `Basis.charging` ∈ `not_applicable / explicit_buy / net_spread`; returns UNAVAILABLE for net-spread LCOS. | **Not imported, duplicated or changed.** `lcos.py` only specifies the receipts a later adapter would feed it. |

Native facts that shape the candidate:

- The native engine already settles an **explicit buy leg** (separate gross sale, charging purchase, auxiliary purchase,
  import and export charges). EXPLICIT_BUY_LEG therefore reads those receipts; it does not re-derive them.
- A **net spread** has no gross buy leg. The candidate reports the gross charging cost as MISSING and never subtracts one.
- Native prices must be non-negative (`number()` rejects negatives); negative-price settlement is not representable natively.
- Round-trip losses, SoC, degradation and conservation live in the native hourly state; the candidate reads `soh_closing`
  and the AC quantities only.

## 2. New (candidate) functionality — `app/bess_commercial_candidate/`

| Module | Content |
|---|---|
| `contracts.py` | Release gate (`ACTIVATION_ENABLED = False`), strict Decimal validators, typed vocabularies, `Decision.OPEN` (the only representable owner-decision state), exact-context decorator, canonical JSON, SHA-256 provenance identity. |
| `charging.py` | `ChargingPeriod`, `ReceiptLeg`, `charging_statement`, `charging_book` (cross-period double-count guards), native adapters, reconciliation with native hourly evidence. |
| `revenue.py` | `RevenueLine` classification (CONTRACTED / CONTRACTED_UNSECURED / MERCHANT), lender presentation mapping (eligibility and haircut OPEN), per-service stacking, one-to-one linkage to allocation claims. |
| `allocation.py` | Energy claims (throughput, merchant), capacity / ancillary reservations (MW, no MWh), reconciliation with native dispatch, double-claim rejection, rated-power cap. |
| `tolling.py` | Typed tolling candidate: capacity, availability fee, term, guarantee, energy ownership, dispatch responsibility, DECLARED deductions, four allocation decisions fixed at OPEN. |
| `augmentation.py` | SOH-threshold / planned / warranty triggers read from native SoH, replacement-CAPEX proposal, funding / residual / CAPEX-class decisions OPEN, posting unconditionally closed. |
| `lcos.py` | LCOS **receipt specification** only (no arithmetic); UNAVAILABLE with reasons when anything is missing. |

## 3. Future adapter boundaries (none is built here)

- **Revenue:** a later reviewed adapter may map `RevenueLine` classes and `present_for_lender` buckets into the revenue authority.
  It must supply the claim linkage and may not bypass the OPEN lender decisions.
- **Financing:** the released CFADS, debt-sizing and DSCR engines are untouched. A financing adapter needs the DSCR eligibility
  and haircut decisions first (B-05/B-06), then consumes the separate class buckets.
- **LCOS:** a later adapter may turn `LcosReceiptSet` into `research/wf09a` `Row`/`Basis` inputs after the methodology decision
  (B-10). Delivered AC discharge MWh is the proposed denominator receipt; its convention is B-10.

## 4. Isolation and preservation facts (verified in the acceptance tests)

- No production module, route, template, static asset, workflow or tool references the package.
- Importing the package loads no `financial_engine`, `finco_core`, `research`, `domain` or web-framework module.
- The existing BESS sources, `finco_core/inputs/bess_native.py` and `research/wf09a/costing.py` are pinned by git blob; the native
  hourly evaluation of the synthetic example is pinned bit-for-bit; the legacy approximation outputs are pinned.
- No protected financing, tax, V10/V11 native, Revenue V2/V3/V4, PPA-01 or React file is modified.
