# FINCO Worked Solar — Canonical Reconciliation Evidence

Purpose: one reproducible institutional worked example using FINCO's existing protected Solar reference and existing production/export authorities. This is evidence documentation, not a second model.

## 1. Canonical case identity

| Field | Canonical value / authority |
|---|---|
| Template source | `generic_solar_reference` |
| Factory | `app.project_factories.create_generic_solar_reference` |
| Project name | Generic Solar Reference |
| Project code | `REF-SOLAR-A` |
| Sponsor | Synthetic Sponsor A |
| Market/country code | `XA` (synthetic) |
| Capacity | 64 MW |
| Financial close | 2030-01-01 |
| Construction | 14 months |
| Operating horizon | 25 years |
| Period frequency | SEMESTRIAL |
| Scenario for canonical reference evidence | Base |

The factory is fictional/public and is intentionally not calibrated to a real client project.

## 2. Reproducible input slice

The canonical factory inherits the standard synthetic Solar assumptions and changes only the protected reference identity/capacity/horizon/construction length.

Key technical/revenue assumptions:

- P50 operating hours: 1,500 h/year;
- annual PV degradation: 0.4%;
- base PPA tariff: 50 EUR/MWh;
- PPA term: 10 years;
- PPA indexation: 2%;
- merchant curve begins at 60 EUR/MWh then 61 EUR/MWh and follows the configured 2% convention thereafter;
- CO2 revenue disabled;
- Solar balancing-cost percentage explicitly zero for this synthetic reference convention.

Hard CAPEX items:

- Solar Modules: 20,000 kEUR;
- Inverters: 3,000 kEUR;
- Civil Works: 5,000 kEUR;
- Grid Connection: 2,000 kEUR;
- Soft Costs: 3,000 kEUR;
- hard CAPEX total: 33,000 kEUR.

Year-1 OPEX input items:

- Technical Management: 150 kEUR;
- Insurance: 100 kEUR;
- Maintenance: 80 kEUR;
- Lease & Tax: 50 kEUR;
- each uses the configured 2% annual inflation convention.

Financing/tax assumptions include:

- gearing cap: 75% of Total Project Uses;
- senior tenor: 15 years;
- base rate: 3.0%;
- margin: 250 bps;
- clean all-in senior rate schedule: 5.5%;
- senior day count: ACT/360;
- target DSCR: 1.20x;
- lock-up DSCR: 1.10x;
- cash-DSRA tenor basis: 6 months;
- sponsor funding mode: `SHARE_CAPITAL_THEN_SHL`;
- gearing basis: `TOTAL_PROJECT_USES`;
- SHL repayment: `CASH_SWEEP` after the senior-debt eligibility boundary;
- corporate tax rate: 25%;
- loss carry-forward: 5 years;
- loss utilisation cap: 100%;
- configured interest-limitation parameter: 30% EBITDA, with 3,000 kEUR minimum-interest threshold;
- clean cash-tax timing enabled.

## 3. Input -> engine -> statements -> returns trace

The canonical trace is:

1. **Inputs** — `app.project_factories.create_generic_solar_reference` returns typed `ProjectInputs`.
2. **CAPEX / construction economics** — typed CAPEX items feed the canonical construction / financing authority.
3. **Sources & Uses** — `financial_engine.financing.project_uses.compute_project_uses` and the G2A financing stack resolve hard CAPEX, financing costs, cash reserve use and sources.
4. **Debt draw / IDC / fees** — the generic financing policy applies construction financing and the initial cash-DSRA policy around the single G2C execution.
5. **Revenue / OPEX** — canonical generation/revenue and OPEX schedules produce period operating economics.
6. **CFADS** — canonical clean CFADS uses EBITDA + financing income - cash tax.
7. **Debt service / DSCR** — senior schedule and sculpting authority calculate interest, principal and covenant DSCR.
8. **Tax** — clean tax authority maps annual tax economics onto the model-period cash-tax convention.
9. **Cash waterfall** — G2C shareholder waterfall applies debt, reserve/distribution gates, SHL and legal equity distributions.
10. **Clean financial statements** — `assemble_decision_complete_financial_statements` assembles typed downstream statement evidence exactly once from that G2C result.
11. **Project return** — decision-complete project-return authority calculates the unlevered dated Project XIRR.
12. **Sponsor return** — gated sponsor-return authority separates share-capital IRR from Total Sponsor XIRR.
13. **Last Run** — a persisted user-project run stores the historical snapshot/composite identity and summary.
14. **Institutional XLSX** — the canonical Last Run exporter reads the committed state; it must not substitute the active draft.
15. **Trust Pack** — API v1.1 / Trust Pack read services compose the committed identity, KPIs, reference-regression evidence, Run Integrity, export metadata, methodology, Signed Run and FINCO Verify as separate authorities.

## 4. Current protected-reference regression snapshot

The following values are already pinned by the current Finance Integrity / P1.2 regression evidence. They are included here as a reviewer-friendly snapshot, not recalculated by Markdown.

| Quantity | Current reference evidence |
|---|---:|
| Hard CAPEX | 33,000.00 kEUR |
| IDC | 544.71 kEUR |
| Commitment fee | 229.70 kEUR |
| Structuring / financing fee | 269.83 kEUR |
| Initial cash DSRA use | 1,933.53 kEUR |
| Total Project Uses | 35,977.78 kEUR |
| Senior debt | 26,983.33 kEUR |
| Share capital | 500.00 kEUR |
| Derived SHL | 8,494.44 kEUR |
| Project IRR / XIRR | 11.768% |
| Share-capital IRR | 45.953% |
| Total Sponsor XIRR | 16.610% |
| Min DSCR | ~1.2486x |
| Average DSCR | ~1.279x |
| First senior interest | 498.82 kEUR |

Rounding in this table is presentation only. Regression tests compare runtime/workbook values with explicit tolerances.

## 5. Reconciliation matrix

The master stream reuses the already-shipped P1.2/P1.3 evidence rather than implementing a parallel workbook or calculation engine.

| Reconciliation | Evidence / authority | Status at this branch base |
|---|---|---|
| Sources = Uses | `tests/test_p1_2_xlsx_export_reconciliation.py::test_xlsx_sources_uses_reconcile`; senior debt must be runtime authority, not residual | PASS |
| No balancing plug | `test_xlsx_sources_uses_not_residual_balanced`; absent senior-debt authority becomes `NOT_AVAILABLE`, never an artificial PASS | PASS |
| Serialized OPEX vs runtime | P1.2 two-sided workbook readback + corruption test | PASS |
| Serialized returns vs runtime | P1.2 Returns readback and corruption tests | PASS |
| Senior debt authority | P1.2 pins current 26,983.33 kEUR clean authority | PASS |
| Working Copy edit vs Last Run | P1.3 real persisted run: draft mutation leaves historical hash/snapshot/engine version/summary unchanged | PASS |
| XLSX same Last Run identity | P1.3 canonical Last Run XLSX: composite hash + run-bound engine version + Project IRR trace to the same committed run | PASS |
| Cross-run identity confusion | P1.3 committed Solar/Wind corruption guard | PASS |
| Debt schedule total vs runtime total debt service | XLSX Reconciliation sheet uses period debt table vs runtime total where available | PASS where authority available |
| Project cash flows -> Project return | clean project-return authority + P1.2 serialized Project IRR trace | PASS for published return metric |
| Sponsor cash flows -> sponsor return | gated sponsor-return authority + P1.2 Share-capital IRR / Total Sponsor XIRR trace | PASS for published return metrics |
| Cash-statement movement | clean C3 statement authority exists, but current institutional XLSX does not bind clean statements into the export bundle | NOT_AVAILABLE in canonical XLSX |
| Balance Sheet balances | clean C3 has typed BS status / residual checks, but current institutional XLSX clean path intentionally leaves statements unavailable | NOT_AVAILABLE in canonical XLSX |
| DSRA movement in institutional XLSX | cash-DSRA authority is typed in G2C/C3, but no dedicated two-sided XLSX DSRA movement reconciliation is currently claimed | PARTIAL |

The last three rows are deliberate non-PASS states. This dossier must not upgrade them to PASS without actual binding/reconciliation evidence.

## 6. Sources & Uses proof

The current Solar reference is gearing-bound on Total Project Uses:

`75% x 35,977.78 kEUR = 26,983.33 kEUR senior debt` (rounded).

The sponsor stack then closes the remaining uses through share capital and derived SHL. Existing P1.2 tests explicitly prove that the old CAPEX-only residual (24,750 kEUR) is **not** the senior-debt authority and that missing debt authority cannot be replaced with a residual plug.

This is the key institutional distinction: a balanced workbook is not evidence if balance was manufactured.

## 7. DSRA proof and wording

The effective cash-DSRA requirement is resolved by the shared reserve-policy authority. For `CASH_DSRA`, the same resolved amount is carried as:

- Project Uses reserve funding;
- the clean cash-DSRA requirement;
- opening operating cash-DSRA balance.

Because the reserve amount enters Total Project Uses, the funding source is determined inside the canonical project funding stack. The Trust Pack therefore avoids the stale blanket phrase “sponsor-funded DSRA.”

For `DSRF`, the Project Uses reserve amount is zero; DSRF sufficiency is separate and actual LoC draws are not modelled.

## 8. Debt roll-forward / sculpting evidence

Senior debt is produced by the clean financing authority, not reconstructed by the export. The workbook debt table and runtime total debt-service reconciliation provide presentation-level traceability, while the underlying senior-debt engine owns opening balance, interest, principal and closing balance.

The critical fail-closed invariant is already part of the Finance Integrity baseline: sculpting may not report `CONVERGED` when CFADS cannot fund the required interest / target debt service.

This master stream does not add a second debt roll-forward formula in documentation.

## 9. Project and sponsor return basis

### Project return

The Project return uses dated unlevered cash flows:

- hard CAPEX construction outflows;
- operating EBITDA inflows;
- unlevered cash tax outflows;
- no senior debt draw/service;
- no SHL draw/service;
- no DSRA funding;
- no financing-cost use in the project-return cash-flow definition.

### Share-capital IRR

Pure legal equity cash flows only: share-capital / share-premium contributions and legal equity distributions. SHL flows are excluded.

### Total Sponsor XIRR

All sponsor funding/receipts exactly once: equity contributions, SHL contributions, legal equity distributions, SHL cash interest and SHL principal receipts.

All three dated return families use the current XIRR date-axis convention rather than a simple equal-period IRR assumption.

## 10. One run — multiple surfaces

For a persisted working project, the intended institutional invariant is:

- Trust Pack Last Run identity / KPI read services;
- API v1.1 Last Run identity / KPIs;
- canonical Last Run institutional XLSX;
- worked reconciliation evidence;

must point to the same historical committed run when they describe the same quantity.

P1.3 already proves the runtime↔XLSX binding using a real V2 run commit, persisted composite hash and run-bound engine version. The Trust Pack composes those same API v1.1 read authorities and does not execute the engine at page render.

A factory-reference workbook is a different evidence class (`FACTORY_REFERENCE`) and must not be described as a persisted user Last Run.

## 11. Working Copy mutation test

Existing P1.3 coverage performs the required same-project journey:

1. create a Solar project from the canonical reference;
2. commit a real run via `v2_atomic_run_commit`;
3. record committed composite hash, snapshot identity, engine version and summary;
4. edit the same project's Working Copy (including tariff change);
5. verify the Working Copy changed;
6. verify historical Last Run identity/summary did not change;
7. export the canonical Last Run and verify the workbook carries that committed lineage.

The master Trust Pack treats this as the authoritative Last Run / Working Copy proof; it does not duplicate the database journey under a new fixture.

## 12. Statement limitation discovered by this master audit

`run_clean_production()` already assembles `CleanProductionRun.financial_statements_result` once. However, the current institutional workbook builder sets its clean-path `statements` bundle field to unavailable instead of binding that existing C3 result. The XLSX P&L, Tax, Cash Flow and Balance Sheet writers therefore intentionally emit unavailable state on the clean path.

This is a presentation/binding gap, not permission to construct new statement maths. Until an app-layer correction binds the existing clean C3 result and reconciliation evidence proves it, the master stream records:

- `CASH_RECONCILIATION = PARTIAL / XLSX NOT_AVAILABLE`;
- `BALANCE_SHEET_RECONCILIATION = NOT_AVAILABLE`.

No completion report may state PASS for those gates at the current base SHA.

## 13. Reproduction map

Focused evidence suites already in the repository:

- `tests/test_p1_1_institutional_trust_pack.py` — methodology/authority registry and conventions;
- `tests/test_p1_2_xlsx_export_reconciliation.py` — institutional XLSX, two-sided reconciliation, serialized readback, run identity;
- `tests/test_p1_3_institutional_validation.py` — real Last Run journey, Working Copy separation, same-run XLSX evidence;
- `tests/test_model_trust_pack_ux.py` — read-only Trust Pack composition/browser acceptance;
- Finance Integrity regression tests — corrected Sources & Uses, debt sizing/sculpting and return terminology.

The master guard test `tests/test_p1_institutional_trust_pack_master.py` protects the canonical identity, authority links and the explicit non-PASS statement limitation without rerunning a parallel finance model.
