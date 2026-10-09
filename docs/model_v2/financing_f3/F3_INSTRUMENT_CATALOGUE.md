# Financing F3 — Proposed Instrument Catalogue

These are **proposed instrument families**, not declarations that FINCO supports each today. "Engine availability"
is the verified state on `main` `1977033`. Presets may share one economic engine where calculations genuinely match.

Legend — Availability: **E** effective today · **P** partial (scalar only) · **N** none (needs new authority).

## Debt

| Instrument | Economic classification | Current FINCO authority | Separate ledger? | Repayment? | Interest? | Availability | Dependency |
|---|---|---|---|---|---|---|---|
| Senior Term Loan | Senior secured debt facility | `FinancingParams` senior fields; `senior_debt` solver | No separate ledger per facility (one schedule) | Yes (sculpted / level / explicit) | Yes (fixed / period schedule) | **E (single)** | F3.1–F3.4 for multiple |
| Construction Facility | Senior debt, construction-period draws, refinanced/converted at COD | Stage B2 draws + IDC on the single Senior | No (draws are Senior draws) | Via conversion to term | Yes (IDC capitalised) | **P** | F3.4 (drawdown schedules) |
| Junior / Subordinated Debt | Debt ranking below Senior | scalar `junior_or_other_project_funding_keur` | **Required** | Yes | Yes | **P (scalar, no economics)** | F3.5 |
| Mezzanine Debt | Subordinated debt, higher margin, possible PIK/bullet | none | **Required** | Yes (bullet/PIK common) | Yes (cash/PIK) | **N** | F3.5; shares the debt-facility engine if PIK/bullet match SHL-like mechanics only after review |
| Shareholder Loan | Related-party debt from sponsor | typed SHL engine (`financial_engine/shl`) | Yes (existing SHL ledger) | Yes | Yes (cash/PIK) | **E (single SHL)** | F3.5 (per-provider SHL) |
| Bond / Institutional Debt | Capital-markets debt, bullet/amortising, fixed coupon | none | **Required** | Yes | Yes | **N** | F3.3/F3.5 (debt-facility preset) |

## Equity

| Instrument | Classification | Current authority | Ledger | Repayment | Interest | Availability | Dependency |
|---|---|---|---|---|---|---|---|
| Common Equity (Share Capital) | Legal equity | `share_capital_keur`; allocator layer 1 | Sponsor ledger by class | No (redemption F4) | No | **E** | F3.5 per provider |
| Share Premium | Legal equity above par | `share_premium_keur`; allocator layer 2 | by class | No | No | **E** | — |
| Additional Equity Contribution | Residual legal equity (EQUITY_ONLY mode) | derived residual; allocator layer 4 | by class | No | No | **E (derived)** | — |
| Other Committed Equity | Committed legal equity before residual | `other_equity_funding_before_shl_keur` | by class | No | No | **E** | per-provider split F3.5 |
| Preferred Equity | Equity with senior claim on distributions / preferred return | **none** | **Required (investor-level)** | Possibly (redemption) | Preferred return | **N — F4 only** | F4 investor waterfall; **not** a decorative return field |
| Strategic Investor | Provider type of common/other equity | none (label only) | By provider | No | No | **N (provider identity)** | F3.5 provider ledger |
| Financial Investor | Provider type | none (label only) | By provider | No | No | **N** | F3.5 |

## Other sources

| Instrument | Classification | Current authority | Availability | Notes |
|---|---|---|---|---|
| Grant / Subsidy | Non-repayable source, reduces funded need; tax/accounting treatment jurisdiction-specific | none | **N** | needs source-allocation + tax/book treatment decision (income vs asset reduction) |
| Deferred Payment | Supplier credit — a deferred *use*, repaid later | none | **N** | liability, not funding; needs working-capital authority |
| Developer Reimbursement / Fee | Project **use** with developer-ledger receipt | Developer Economics V1 | **E** | a use, not a source; unchanged by F3 |

## Per-entry treatment (proposed)

| Instrument | Tax | Financial statements | Sponsor-return | Priority / waterfall | S&U |
|---|---|---|---|---|---|
| Senior Term Loan | interest deductible subject to ATAD/limitation; fees per capitalisation policy | liability; interest expense / capitalised IDC | none (third-party) | first claim after opex/tax | source (draw), use (IDC/fees) |
| Construction Facility | IDC capitalised into asset basis | liability during construction | none | as Senior | source/use as Senior |
| Junior / Sub Debt | deductible subject to limitation; ranked after Senior | liability | none | after Senior DS, before distributions | source |
| Mezzanine | as Junior; PIK interest accrues to balance | liability | none | after Junior | source |
| Shareholder Loan | per `ShlInterestDeductibilityMode` / `ShlAccountingTreatment` | liability (or equity per policy) | **Total Sponsor** SHL interest/principal | after Senior DS, before legal-equity distributions | source (SHL cash) |
| Bond | as Senior | liability | none | pari passu or ranked by seniority | source |
| Common Equity / Premium / Additional | not deductible | equity | **Pure Equity** contributions | residual claimant | source |
| Preferred Equity | not deductible (dividends) | equity (or liability if redeemable) | requires investor ledger (F4) | before common (F4) | source |
| Grant | per jurisdiction | deferred income or asset reduction | none | n/a | source |
| Deferred Payment | n/a | trade payable | none | n/a | deferred use |

## Preset sharing rule

One *debt-facility* engine: balance roll-forward, interest on a rate schedule, drawdown schedule, repayment schedule
(bullet / level / sculpted / explicit / sweep), fees, grace. Senior, Construction, Junior, Mezzanine and Bond presets
differ in **defaults, seniority rank, permitted repayment modes and covenant eligibility** — not in arithmetic.
SHL keeps its existing engine until a reviewed equivalence shows it can be expressed as a debt-facility preset
(it has inclusive day-count and distinct tax semantics today). Preferred Equity gets no engine in F3.
