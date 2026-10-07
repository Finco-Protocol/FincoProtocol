# Developer Economics V1 — Contract

Typed, end-to-end Developer Economics authority. Developer economics is a
**separate ledger** linked to, but never merged with, the project and sponsor
ledgers.

## Three distinct economic concepts

| Concept | Project ledger | Developer ledger |
|---|---|---|
| A. Development spend (dated, pre-FC) | — | negative dated cash flow |
| B. Development cost reimbursement | project **use** | positive receipt at Financial Close |
| C. Developer fee | project **use** | positive receipt at Financial Close |

B and C are never collapsed into one field. Both are project uses that raise
total project uses; the financing policy (gearing, senior sizing, sponsor
funding) decides how they are funded. The contract never claims that the fee
reduces the sponsor equity requirement.

## Typed input

`finco_core.inputs.development.DevelopmentEconomicsInput`, carried as the optional
`ProjectInputs.development_economics` (default `None` = disabled no-op).

Fail-closed validation: finite non-negative numerics, strict `bool`, real dates in
strictly increasing order, reimbursement ≤ eligible (spent) amount, abandoned
case carries no receipts, enabled-but-empty input rejected, percentage fee in
`[0, 1]`. Spend dates after the canonical Financial Close are rejected by the
calculator (`DEV_ECON_SPEND_AFTER_FINANCIAL_CLOSE`).

Serialization key `development_economics` is emitted only when configured, so
existing payloads are byte-identical. Absent and disabled both hash to `None`.

## Dating

* Spend carries explicit typed dates supplied as input facts (the developer's own
  pre-FC cash); every date must be on or before the canonical FC date.
* Reimbursement and fee settle at the canonical `ProjectInfo.financial_close`.
  No "N months after FC" timing exists.

## Fee basis (non-circular)

* `FIXED_KEUR`: fee = value.
* `PCT_OF_HARD_CAPEX`: fee = fraction × `CapexStructure.hard_capex_keur`. The basis
  is a pure CAPEX input, evaluated before financing costs, reserves and developer
  uses; it excludes the fee by construction. A percentage of total project uses is
  intentionally not offered (it would be circular).

## Project-use treatment

`compute_project_uses` (the single Sources & Uses composition point) adds
`development_cost_reimbursement_keur` and `developer_fee_keur` to
`ProjectUses` and to `total_project_uses_keur`. The G2A fixed point, senior debt
sizing, IDC and sponsor funding therefore respond through existing logic.

* The unlevered project return keeps its hard-CAPEX-only methodology and records
  the developer uses explicitly as `excluded_developer_economics_uses_keur`
  (never `UNCLASSIFIED`).
* The developer uses are capitalised into the book depreciable asset basis as two
  `civil_grid` components so the balance sheet stays balanced.

## Developer metrics

* IRR = XIRR over the developer's own dated vector. `UNAVAILABLE` (typed status,
  value `None`) without a valid sign change; never −100 % or 0 %.
* MOIC = (reimbursement + fee) / spend. `0.0` when spend > 0 and receipts = 0;
  typed `ZERO_CONTRIBUTION` (value `None`) when spend = 0.
* Developer flows never enter sponsor contributions/distributions, Pure Equity
  cash flows or the shareholder waterfall.

## Surfaces

Assumption register section `DEVELOPER`, calculation-trace entries, and canonical
analytics category `DEVELOPER` (spend, reimbursed cost, fee, receipts, MOIC, IRR
with availability/status), all derived from the single calculator result.

## Deferred

User-editable inputs in the workbook UI need sibling-owned presentation files
(router, workbook template, smart panel) and are intentionally not part of V1.
