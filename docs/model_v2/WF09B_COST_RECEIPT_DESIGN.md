# WF-09B — Canonical Cost Receipts & LCOE/LCOS Reconciliation (Candidate V0)

**Status:** release-closed, non-authoritative, read-only candidate. Authority string
`WF09B_COST_RECEIPTS_CANDIDATE_V0`. `ACTIVATION_ENABLED` is a literal `False`; every
`evaluate()` raises `WF09B_RELEASE_CLOSED`. No route, Run schema, persistence,
exported metric, frontend component or flag uses it, and nothing imports it.
Canonical analytics keeps reporting `lcoe` as `AUTHORITY_MISSING`.

Package: `app/model_v2/costing_wf09b_candidate/`. Tests:
`tests/test_costing_wf09b_candidate.py`. Decisions:
`docs/model_v2/WF09B_FINANCIAL_OWNER_DECISIONS.md`.

## 1. Relationship to WF-09A (no second formula)

The only arithmetic is `research.wf09a.costing.calculate` (read-only import; the
file is byte-identical to `main`). WF-09B adds a receipt layer in front of it and a
reconciliation layer behind it:

```
Run/axis/cost/energy/discount receipts ──validate/atomise──▶ wf09a.Row tuple
                                                              │ calculate()
independent re-derivation from receipts ◀──── reconcile ◀─────┘
```

WF-09A still decides UNAVAILABLE for missing convention / rate source / no positive
discounted energy; WF-09B adds the evidence checks WF-09A cannot see (identity,
alignment, double counting, cash-movement-vs-cost, charging basis).

## 2. Inspected canonical structures and the receipt each maps to

| Receipt | Mirrors / consumes (inspected) | What the canonical source actually exposes today |
|---|---|---|
| `RunReceipt` / `RunIdRef` | `app/model_v2/assumption_register.py::RunIdentity` (`snapshot_id`, `composite_hash`, `workbook_version`, `engine_version`, `project_id`, `scenario_id`) | identity fields exist; **freshness, calculation authority and evidence completeness are not fields of RunIdentity** — supplied by the caller, never inferred |
| `PeriodAxis` | `financial_engine/results.py::OperatingPeriodResult` (`period_index`, `period_start`, `period_end`, `is_construction`, `days_in_period`) | exact dates and phase exist per period; the receipt only validates ordering/contiguity (rows cover `(start, end]`) |
| `CostLine` OPEX | `OperatingPeriodResult.opex_keur` / `OperatingSchedules.opex_keur`; `total_opex_keur` in canonical analytics | **one aggregate per period; no source-line identities** |
| `CostLine` cash tax | `TaxAndCfadsSchedules.corporate_tax_cash_keur` (cash) vs `tax_keur` (accrual) | cash tax is available per period; accrual and depreciation are distinct fields and are never costs here |
| `CostLine` CAPEX / IDC / financing / reserve | `financial_engine/financing/project_uses.py::compute_project_uses` → `ProjectUses` (hard capex, `idc_keur`, `commitment_fees_keur`, reserve funding, developer uses) | **totals at financial close, not period-timed lines with origin ids** |
| `CostLine` DEVEX | `financial_engine/developer_economics` uses (reimbursement/fee) | no DEVEX line with a capitalisation flag exposed to Run results |
| `EnergyLine` | `OperatingPeriodResult.production_mwh` | a production quantity per period; **no stated delivered/exported boundary and no curtailment/loss/auxiliary breakdown** |
| `DiscountReceipt` (valuation date + `factors_as_of`) | `financial_engine/valuation/model.py::discount_dated_cashflows` / `project_npv` policy | NPV policy exists but is `NOT_CONFIGURED` on the references; **no approved LCOE valuation origin, factors or convention** |
| BESS charging | `domain/bess/settlement.py` / `financial_engine/bess.py` native receipts (WF-09A §BESS) | native receipts exist; **not wired to a Run cost line, and the WF-08 candidate is intentionally not imported** |

## 3. What is genuinely calculable today

* **Calculable:** any request whose receipts are explicitly supplied and internally
  consistent — Solar/Wind unlevered and levered after-tax, BESS LCOS with explicit
  paid charging — proven with hand-calculated synthetic evidence.
* **Not calculable from today's canonical Runs (reference parity is NOT assessed and
  is not reported as PASS):** the reference Solar/Wind Runs lack atomised OPEX lines,
  period-timed CAPEX/IDC/DEVEX with origin identities and capitalisation flags,
  financing interest/fee period lines, a stated delivered-energy boundary, an
  approved discount origin, and freshness/completeness attestations. Each is listed
  as a future receipt in §7. `REFERENCE_PARITY` is the constant
  `NOT_ASSESSED_MISSING_LINE_LEVEL_EVIDENCE`.
* **Unavailable by design:** Data Center and EV Charging (no approved physical
  denominator; energy is not the economic unit), augmentation and lifecycle
  replacement CAPEX, net-spread-only LCOS.

### Valuation origin (Correction A)

`valuation_date` is mandatory evidence: `None` ⇒ UNAVAILABLE
`WF09B_VALUATION_DATE_MISSING`. It is never inferred from the Run date, the first
operating period, financial close, the axis, the discount convention text or the
factor schedule's own origin. Compatibility with the supplied factor contract is
checked through `factors_as_of` (the date the factor schedule itself discounts to):
missing ⇒ UNAVAILABLE `WF09B_FACTOR_VALUATION_ORIGIN_MISSING`; different from the
valuation date ⇒ `WF09B_VALUATION_ORIGIN_MISMATCH` (inconsistent evidence). No
factor magnitude is judged (rates, signs and conventions stay Financial Owner
decisions). Supplying a valid origin leaves every existing result unchanged.

## 4. Double-counting and cash-vs-cost rules

* Every line has a unique `line_id` (the WF-09A source identity) and an `origin_id`
  unique among ATTRIBUTED lines. A line that already includes other origins (DEVEX
  or IDC capitalised into CAPEX) declares them in `contains`; the contained origin
  may not be attributed elsewhere (`WF09B_DOUBLE_COUNT`, `WF09B_DUPLICATE`).
* Principal repayment, debt drawdown, equity funding, reserve funding, depreciation,
  accounting tax expense, distributions and net arbitrage spread can only be recorded
  as `EXCLUDED_MOVEMENT` memos (`WF09B_CASH_MOVEMENT_NOT_COST`). A cash movement never
  becomes a cost automatically.
* Cash tax: paid ≥ 0, refund ≤ 0 (a credit keeps its sign); no other kind may be negative.
* Unlevered metric: attributed finance/tax lines are rejected; WF-09A receives
  definitional-exclusion origins (`wf09b:definitional-exclusion:…`) for those two
  components. This is a metric definition, not a substitute for missing evidence.
* Levered / LCOS: every component needs an explicit line (zero allowed) in every
  period; absence is `WF09B_COMPONENT_EVIDENCE_MISSING`.
* Energy: only supplied delivered energy; a gross/curtailment/loss/auxiliary breakdown
  is accepted only if it reconciles exactly; any generic RTE/loss haircut is rejected
  (`WF09B_SYNTHETIC_ENERGY_ADJUSTMENT`), so efficiency losses cannot be applied twice.

## 5. Reconciliation

After WF-09A returns, the layer independently recomputes, from the receipts and
exact Decimals at fixed 50-digit precision: per-component discounted cost, the
numerator (= sum of attributed discounted lines), the discounted energy, and checks
that the five component EUR/MWh values sum to the total within
`COMPONENT_SUM_TOLERANCE = 1e-30`. WF-09A divides at 50 significant digits, so each
quotient carries ≤ 5e-41 absolute rounding for values below 1e9 EUR/MWh; five
components give < 3e-40; 1e-30 is a generous bound with no economic meaning. Any
mismatch raises `WF09B_RECONCILIATION_FAILED` (proven by tampering tests).

## 6. Fail-closed matrix

Raises (inconsistent or malformed evidence): Run identity mismatch across receipts, factors discounted to a date other than the valuation date (`WF09B_VALUATION_ORIGIN_MISMATCH`),
unknown period, misaligned/overlapping/gapped axis, currency ≠ EUR, real/nominal
mismatch, energy boundary ≠ vertical boundary, charging kinds outside BESS,
duplicate identities, cash movement attributed as cost, synthetic energy adjustment.
Returns UNAVAILABLE (missing or unapproved evidence): stale/incomplete Run, missing
convention / rate source / factor / valuation date / factor valuation origin, missing amount, missing component or energy
period, zero discounted energy, net-spread-only or missing charging cost,
augmentation/replacement CAPEX or unknown augmentation status, Data Center / EV
Charging, metric not supported by the vertical.

## 7. Future Run integration dependency map (not in this PR)

1. Atomised period OPEX lines with source identities (today only `opex_keur` aggregate).
2. Period-timed CAPEX / IDC / DEVEX lines with origin ids and capitalisation flags
   (today `ProjectUses` totals + separate spending profile).
3. Financing interest / fee period lines and IDC capitalisation boundary
   (WF-07 / F3.1 supply schedules as evidence; no cross-import).
4. Cash-tax lines from `corporate_tax_cash_keur` with refunds (WF-10 Tax supplies the
   policy; no cross-import).
5. A delivered-energy receipt with an explicit physical/commercial boundary and
   actual curtailment/loss/auxiliary evidence.
6. An approved valuation origin: factors, convention, nominal/real basis, valuation date.
7. Run freshness and evidence-completeness attestation beside `RunIdentity`.
8. BESS: native settlement receipts mapped to paid charging / grid / auxiliary lines
   (after WF-08 approval), plus an approved augmentation/replacement posting basis.
9. An independent authority decision and product release before any exposure; until
   then canonical analytics keeps `lcoe` as `AUTHORITY_MISSING`.

## 8. Verification summary

93 focused tests with `Fraction` hand-calculated expectations; 32 guard mutations
all caught; blob pins for `research/wf09a/costing.py`, `domain/analytics/lcoe.py`,
`app/model_v2/canonical_analytics.py`, `financial_engine/orchestrator.py`,
`financial_engine/tax/engine.py`, `financial_engine/bess.py`; import isolation by AST
and `sys.modules` delta; nothing outside the package refers to it.
