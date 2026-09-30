# FINCO Model — Institutional Methodology and Conventions

Status: canonical institutional narrative for the FINCO Model Trust Pack.

This document explains the implemented FINCO calculation and evidence path. It is not a second calculation specification. Where a machine-readable metric definition exists, `app/model_methodology_registry.py` remains the product convention authority; financial calculations remain owned by `financial_engine/**` and `finco_core/**`.

## 1. Authority hierarchy

The institutional evidence path is intentionally layered:

1. **Typed project inputs** define the economic assumptions.
2. **Clean production calculation** executes once through `app.services.production_financial_authority.run_clean_production` and the G2C shareholder-waterfall entry point.
3. **Clean financial statements authority** is assembled once downstream of that same G2C result by `financial_engine.financial_statements.assemble_decision_complete_financial_statements`. Statements never feed back into debt sizing, tax, distributions, returns, or valuation.
4. **Committed Last Run** persists the historical run identity and summary. Editing a Working Copy does not rewrite that evidence.
5. **API v1.1, Trust Pack and canonical Last Run XLSX** read the committed evidence through their existing read authorities; they do not create a second model.
6. **Reference Regression Check**, **Run Integrity**, **Signed Run**, and **FINCO Verify** are separate authorities and must not be conflated.

`financial_engine/**` and `finco_core/**` are frozen for this Trust Pack stream. Documentation must follow runtime behavior; runtime behavior is not changed to make the documentation simpler.

## 2. Model architecture

The standard production flow is:

`ProjectInputs -> production authority classification -> generic financing policy -> G2C project/shareholder waterfall -> decision-complete returns -> clean financial statements -> presentation/persistence`

The production seam executes one clean financial calculation for a promoted input. A blocked input fails closed rather than falling through to an alternate production engine.

The generic financing policy may resolve construction financing and the cash-DSRA requirement around the single G2C entry point. The resulting evidence includes the financing-policy authority and whether construction financing / cash DSRA were applied.

## 3. Time periods and construction/operations

The public generic Solar reference uses `PeriodFrequency.SEMESTRIAL` for the standard model axis. Its protected reference identity is:

- template source: `generic_solar_reference`;
- model code: `REF-SOLAR-A`;
- capacity: 64 MW;
- financial close: 2030-01-01;
- construction: 14 months;
- horizon: 25 years.

Construction financing has its own typed construction-period dates and native funding grain. It must not be silently reallocated onto a different model axis merely for presentation. Operating outputs use the model period axis. Annual financial-statement or tax views are aggregations/periodisations of the underlying model evidence; they are not a claim that the engine itself runs only annually.

Tax is annual in economic authority but cash timing is mapped to model periods. The current registry describes the standard clean convention as annual tax with cash settlement in the final model period of the tax year; the model also has an explicitly typed lender-case periodisation mode where configured.

Partial first/last years and terminal periods therefore follow the dates carried by the canonical period engine, not a hand-maintained annual spreadsheet convention.

## 4. Nominal / real convention

FINCO consumes the escalation/inflation assumptions supplied in the typed inputs. The public generic Solar reference uses nominal tariff / market-price escalation and OPEX inflation assumptions. This Trust Pack does not introduce a separate real-to-nominal conversion layer. A user or reviewer should treat the model as nominal where nominal escalators are configured unless a specific typed input contract states otherwise.

## 5. CAPEX and Total Project Uses

Canonical Total Project Uses are computed by `financial_engine.financing.project_uses.compute_project_uses`:

`Total Project Uses = hard project CAPEX + explicit financing-cost uses + cash reserve funding + other explicit uses`.

For the current generic cash-DSRA product path, explicit financing-cost uses include the applicable IDC and lender/financing fees. Gearing can therefore be measured against Total Project Uses rather than hard CAPEX alone. Senior debt must never be manufactured as a residual simply to make Sources & Uses balance.

The current Finance Integrity reference baseline for Solar records:

- hard CAPEX: 33,000.00 kEUR;
- IDC: 544.71 kEUR;
- commitment fee: 229.70 kEUR;
- structuring/financing fee: 269.83 kEUR;
- initial cash DSRA use: 1,933.53 kEUR;
- Total Project Uses: 35,977.78 kEUR;
- senior debt: 26,983.33 kEUR;
- derived shareholder loan: 8,494.44 kEUR;
- share capital: 500.00 kEUR.

Those values are regression evidence for the protected synthetic reference, not a replacement arithmetic engine in this document.

## 6. Sources & Uses and construction funding

The G2A sponsor/funding stack reconciles fixed sources to Total Project Uses and derives the residual sponsor instrument according to the typed `SponsorFundingMode`.

For `SHARE_CAPITAL_THEN_SHL`, the residual after senior, junior, share capital, share premium and other committed equity becomes SHL cash principal. For `EQUITY_ONLY`, it becomes additional equity. The construction funding schedule then allocates the already-defined sources across uses and fails closed if aggregate sources do not equal uses.

The generic construction funding waterfall is capital-class transparent. It is not a balancing plug.

## 7. DSRA / DSRF truth

The current cash-DSRA authority is `financial_engine.financing.reserve_policy.resolve_cash_dsra_requirement_keur`.

For `CASH_DSRA`, the resolved requirement is a **Project Use** and is also the opening cash-DSRA requirement. The invariant is that the resolved requirement equals the Project Uses reserve funding amount and the opening operating cash-DSRA balance.

This does **not** justify a blanket statement that DSRA is always a separate sponsor-funded line. Once included in Total Project Uses, it is funded through the canonical project funding stack together with the other uses. The exact source allocation is determined by the funding policy / construction funding authority for the run.

For `DSRF`, no cash reserve is funded at close; DSRF sufficiency is a separate support concept. Actual LoC draw mechanics are a known institutional gap and must not be implied.

A future business-policy decision may change how a project chooses to fund DSRA, but that is outside this Trust Pack and must not be implemented by silently altering the waterfall.

## 8. Revenue, OPEX, EBITDA and working capital

For Solar/Wind, generation revenue follows the machine-readable methodology registry and the canonical generation/revenue modules. OPEX follows the typed OPEX projection schedule and configured inflation. EBITDA is revenue less operating expenses.

The generic Solar reference uses:

- 1,500 P50 operating hours;
- 0.4% annual degradation;
- 50 EUR/MWh base PPA tariff;
- 10-year PPA term;
- 2% PPA indexation;
- synthetic merchant curve starting at 60 / 61 EUR/MWh then escalating by the configured market convention;
- Year-1 nominal OPEX inputs of 150 + 100 + 80 + 50 kEUR before escalation.

No general working-capital module is claimed by this document unless a specific runtime contract exposes it. Absence of a working-capital line must not be described as a zero economic requirement for every project.

## 9. CFADS and DSCR

Authoritative clean CFADS is calculated by `financial_engine.cfads.calculate_canonical_cfads` and is pre-debt-service / pre-DSRA:

`CFADS = EBITDA + financing income - cash tax paid`.

Authoritative clean DSCR is `CFADS / debt service` on periods with debt service. Periods without debt service do not manufacture an infinite covenant metric in the sizing authority.

The legacy standalone utility that divides EBITDA by debt service is not the clean sizing/covenant authority and must not be used to explain production debt sizing.

## 10. Senior debt draw, IDC, fees and sculpting

Senior sizing is constrained by the typed financing contract. In the generic reference path, the commitment is the feasible result of the configured gearing and DSCR capacity rules.

The corrected debt-sculpting invariant is fail-closed: FINCO must not report a converged sculpting solution when CFADS cannot fund the required interest / target debt service. The current Data Center reference history contains an example of the prior false-convergence state that was corrected; the Trust Pack does not reintroduce it.

Senior interest uses the configured clean interest schedule. The generic Solar reference uses a 5.5% all-in rate (3.0% base + 250 bps margin) and ACT/360 day count. The Finance Integrity baseline records 498.82 kEUR first-period senior interest on the current larger senior balance.

The generic Solar reference configures a 15-year senior tenor, 1.20x target DSCR, and 1.10x distribution lock-up DSCR. If gearing binds before DSCR capacity, realised minimum DSCR can sit above the target.

## 11. Shareholder loans and sponsor funding

FINCO distinguishes:

- **share capital** — legal equity contribution;
- **shareholder loan (SHL)** — sponsor debt instrument with its own interest/principal cash flows;
- **aggregate sponsor funding** — the combined sponsor sources used to fund the project.

For the current generic Solar reference, the runtime G2A stack derives SHL principal as the residual required by Sources & Uses; the factory's older SHL amount is not the production funding authority. The clean Solar repayment policy is `CASH_SWEEP`, with repayment eligibility after senior debt and a typed terminal maturity.

SHL cash interest, PIK and principal are separate waterfall movements. SHL is debt for accounting purposes and is not silently treated as retained earnings or share capital.

This is an economic-model description only; it is not a legal, tax or thin-capitalisation opinion.

## 12. Tax

The clean tax authority uses typed tax inputs and model-period mapping. The generic Solar reference currently configures a 25% corporate tax rate, five-year loss carry-forward, 100% loss-utilisation cap, a 30% EBITDA interest-limitation parameter and a 3,000 kEUR minimum-interest threshold.

Taxable income, tax depreciation, loss usage, interest deductibility where implemented, accrual and cash-tax timing are model mechanics. FINCO does not claim that the generic tax contract implements every jurisdiction-specific tax rule. Country-specific interest-limitation and other local rules remain explicit gaps unless a dedicated typed authority exists.

## 13. Financial statements and cash waterfall

The clean production run already owns a Phase C3 `financial_statements_result`, assembled exactly once downstream of the G2C result. Its contracts explicitly separate:

- income statement;
- tax bridge;
- project-finance cash waterfall (not an IAS 7 statutory cash-flow statement);
- fixed-asset roll-forward;
- retained earnings;
- balance sheet;
- typed statement status / unavailable reasons.

The statement authority is strictly downstream and cannot feed back into model economics.

**Current institutional-export limitation:** `app/export/institutional_workbook.py` does not presently bind the clean `financial_statements_result` into its `WorkbookExportBundle` for the clean G2C path; it intentionally emits statement/tax sections as unavailable there. Accordingly this Trust Pack does not claim that the current canonical XLSX proves a Balance Sheet reconciliation or full cash-statement reconciliation. Closing that presentation/binding gap requires a separate reviewed app-layer correction; it must not be faked by a new calculation or balancing plug.

## 14. Project and sponsor returns

Terminology is strict:

- **Project IRR / Project XIRR**: unlevered dated return over hard-CAPEX construction outflows and operating EBITDA less unlevered cash tax. Financing costs, debt, SHL and DSRA are excluded from the project-return cash-flow definition.
- **Share-capital IRR (equity only)**: dated XIRR over legal equity contributions and legal equity distributions; excludes SHL flows.
- **Shareholder-loan return**: the SHL instrument's own cash-interest / PIK / principal economics; it is not the share-capital IRR.
- **Total Sponsor XIRR**: dated XIRR over all sponsor funding and receipts, including share capital and SHL flows exactly once.

FINCO uses dated XIRR semantics for these return authorities. The year-fraction convention is actual calendar days from the first cash-flow date divided by 365 (fixed-denominator ACT/365F-style convention), as recorded in the methodology registry.

The current protected Solar regression snapshot records Project IRR 11.768%, Share-capital IRR 45.953% and Total Sponsor XIRR 16.610%.

## 15. Last Run, Working Copy and run identity

A Working Copy is mutable. A Last Run is historical committed evidence.

A Working Copy edit after a run must not mutate the committed Last Run composite hash, snapshot identity, engine version or persisted summary. The canonical Last Run XLSX authority reads the committed snapshot and its run-bound identity; it does not silently switch to the active draft.

Where a true persisted run UUID is unavailable, a snapshot identifier must not be relabelled as a run UUID. `last_runtime_snapshot_id`, `last_runtime_composite_hash`, `run_id`, engine version and evidence/certificate identity are distinct fields.

Factory-reference exports are explicitly `FACTORY_REFERENCE`; they are not mislabeled as a persisted `CANONICAL_LAST_RUN`.

## 16. Scenario semantics

Scenarios are input mutations applied through the shared scenario authority before the single clean production calculation. A Last Run is bound to the scenario and assumptions that were committed at that run. Editing the active Working Copy or changing the active scenario later does not retroactively alter historical evidence.

## 17. Evidence vocabulary

The four commonly confused trust concepts mean different things:

- **Reference Regression Check** — executes canonical reference/reconciliation checks against pinned expected values. It protects regression behavior; it is not independent validation of a user's economic assumptions.
- **Run Integrity** — checks internal consistency of the committed Last Run evidence. It does not prove market identity or real-world truth.
- **Signed Run** — cryptographically signs a run-evidence payload/provenance envelope. A valid signature proves integrity/authenticity of that payload, not economic correctness and not FINCO Verify status.
- **FINCO Verify** — separate source-proven model/market binding authority. It is never implied by Reference Regression, Run Integrity or Signed Run.

## 18. Institutional XLSX

The canonical institutional workbook is the existing exporter in `app/export/institutional_workbook.py`. No second spreadsheet model exists in this Trust Pack.

Its established sheets include Inputs, CAPEX, OPEX, Revenue, Senior Debt, SHL, Returns, Run Identity and Reconciliation, plus statement/tax surfaces that may be explicitly unavailable on the clean path as described above.

The Reconciliation sheet performs two-sided checks by reading serialized workbook cells and comparing them with runtime authority. It must not compare a value with itself and must not create a residual senior-debt plug.

## 19. Worked Solar evidence

The canonical worked case is documented in `docs/trust/FINCO_WORKED_SOLAR_RECONCILIATION.md`. It reuses existing reference factories, runtime, P1.2 XLSX tests and P1.3 persisted-Last-Run tests. The document does not maintain an independent economics model.

## 20. Known limitations / deferred policy questions

This Trust Pack deliberately does not change:

- cash-DSRA business funding policy;
- DSRF draw mechanics;
- jurisdiction-specific tax engines;
- clean financial-statement accounting authorities that are typed unavailable;
- institutional XLSX clean-statement binding;
- engine performance;
- Data Center sensitivity design;
- multitenancy;
- Model↔Market production Verify activation;
- token metering or token utility;
- final global Product Truth release reconciliation.

When an authority is unavailable, the institutional surface must say `NOT_AVAILABLE` / typed unavailable rather than manufacturing a pass.
