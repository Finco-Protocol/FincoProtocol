# Financing F2: Senior Debt Bankability V2

## Provenance and Ownership

- Audited canonical main: `1977033da8967a93d581d6407337798dc0a44aad`.
- Feature branch: `feat/model-v2-financing-f2-bankability`.
- Delivery: one consolidated Draft PR; exact feature HEAD, PR URL and exact-head CI run links are recorded in its delivery body. No merge or deployment.
- PRs #224-#228 were independently confirmed merged before work began.
- Parallel F1: Draft #230, `feat/model-v2-financing-f1-sources-uses`; its eight changed files do not overlap F2.
- Parallel F3: Draft #229, `feat/model-v2-financing-f3-foundation`; contract work is not modified here.
- No edits to F1-owned Sources & Uses projections/router, investor template or `main_web.py`.
- ZERO DIFF required and checked for `financial_engine/`, `finco_core/`, `domain/`, Radar, Yield, Crypto and Protocol. No schema, migration, worker or financial-equation changes.

## Operational Capability Matrix

| Capability | Working editor / canonical effect | Boundary |
|---|---|---|
| Lender case | P50 / P90-10Y via typed `DebtSizingCaseConfig` | Solar/Wind only; never changes operating yield case |
| Sizing | FLAT_DSCR_SCULPTED with Total Project Uses gearing cap; GEARING_CAP with level principal | Existing clean solver only; selecting a method explicitly selects its stated repayment contract |
| Gearing / tenor | Existing registry editors retained and consumed | Requested cap is not actual debt; incompatible explicit vectors reject tenor edits |
| Scalar DSCR | Explicit scalar fallback and target | Existing scalar financing field is locked when the linked configuration owns target authority |
| Period DSCR | Complete target vector, actual dated operating periods | SEMESTRIAL; exact tenor * 2 entries; FLAT_DSCR_SCULPTED only |
| Interest | Complete explicit annual all-in percentage vector; ACT/360 or ACT/365 | One percent-to-fraction conversion in Python; no global legacy-rate precedence change |
| Fees | Commitment, structuring, arrangement percentages | Only generic construction policy without competing manual costs or explicit construction pricing |
| Reserve | NONE, fixed CASH_DSRA, DSRF standby commitment/fee, generic automatic peak forward coverage | Legacy CAPEX reserves stay locked; no DSRF draw/replenishment engine |
| Evidence | Existing persisted debt schedule, CFADS/Senior service, reserve balances/funding/release, immutable Last Run KPIs | Missing sizing verdict/constraint presentation remains explicitly unavailable, never reconstructed |
| Integrity | Existing institutional integrity surface unchanged | Solver convergence does not imply bankability; freshness and integrity remain separate |

## Exact Input Contract

The new BOUND registry field `debt.bankability.configuration` maps to `bankability_config_json` in the existing scalar snapshot. This is a registered Run-consumed input, not a sidecar or metadata-only field. It uses existing authorized CAS persistence; no table or migration is added. Registry version is unchanged: snapshots without the optional field keep their existing identity and input behavior.

`app/workbook/bankability_config.py` validates the bounded version-1 JSON and converts it to existing frozen domain dataclasses with `dataclasses.replace`. The canonical snapshot adapter applies it after existing scalar/technology adapters. Both Run and canonical Last Run input/export restoration use that same adapter or the existing serialized effective ProjectInputs.

| Payload | Typed authority | Units / validation |
|---|---|---|
| `version` | Application serialization contract | Exactly integer 1; duplicate/unknown keys rejected |
| `sizing_mode` | `FinancingParams.debt_sizing_mode`, `gearing_basis_mode`, `gearing_cap_repayment_method` | Executable modes only; Total Project Uses; explicit method choice selects level-principal gearing policy |
| `lender_case` | `debt_sizing_case.production_yield_scenario` | Exact `P_50` / `P90-10y`; other sizing-case inputs retained |
| `targets` | `senior_sculpting_config.target_dscr_schedule` | Full vector 1-3x; empty vector explicitly selects scalar fallback |
| `target_scalar` | `FinancingParams.target_dscr` | 1-3x; only with explicit empty target vector |
| `rates_pct` | `senior_debt_interest_config.rate_schedule.explicit_all_in_rates` | 0-20%; Python divides by 100 exactly once; full vector |
| `day_count` | `SeniorDayCountConvention` | `act_360` / `act_365` |
| `fees.commitment_pct` | `FinancingParams.commitment_fee` | 0-10% annually on undrawn Senior |
| `fees.structuring_pct`, `fees.arrangement_pct` | Corresponding FinancingParams fields | 0-10%; summed once by existing construction policy on Senior + VAT commitments, settled at FC |
| `reserve.mode` | `DebtServiceReserveSupportMode`, `dsra_target_policy` | Supported combinations only |
| `reserve.months` | `dsra_months` | Whole 1-12 for automatic peak; 0 otherwise |
| `reserve.requirement_keur` | `debt_service_reserve_requirement_keur` | Finite 0-1,000,000 kEUR; prohibited under NONE/automatic |
| `reserve.commitment_keur`, `reserve.fee_pct` | DSRF commitment and annual fee | Commitment covers requirement; 0-10%; prohibited for cash reserve/NONE |

Omitted keys inherit existing authority. Blank configuration explicitly removes the entire override; it does not alter historical Run inputs. Invalid vectors or reserve combinations fail before persistence. Validation repeats on the freshly read PIS inside the existing exclusive CAS transaction, protecting concurrent Save. Invalid input is surfaced as a field error, not a partial save or engine invocation.

The grouped configuration is project-owned (`ScenarioPolicy.NOT_ALLOWED`), explicitly labeled shared across scenarios. Saving on a selected scenario does not rewrite its overrides; project-input identity changes invalidate applicable Run freshness. This PR does not claim a new per-scenario financing configuration namespace. Existing scenario tariff/CAPEX/OPEX and scalar authorities are not redesigned.

## Fees, Construction and Reserves

- No new IDC, fee, debt-sizing, tax, reserve or return equation is implemented.
- Existing H1 generic construction policy derives construction rates from the operating explicit rate authority when no explicit construction contract exists.
- Commitment fee accrues on undrawn commitment; structuring plus arrangement fees are capitalized exactly once. Conflicting manual financing CAPEX/explicit construction pricing is rejected rather than cleared.
- Fee editability and Save also inspect the existing authorized user-sub-line/active-scenario CAPEX fold. Run rechecks the final materialized inputs before invoking the engine. A later manual financing CAPEX addition cannot silently deactivate a previously saved fee override; it must be removed explicitly.
- Automatic peak reserve uses existing canonical funding/sizing fixed point. The editor does not calculate its amount.
- Fixed cash reserve enters initial Uses; standby DSRF is not cash-funded in Uses. DSRF fee uses existing post-Senior treatment and maturity expiry.
- NONE explicitly supplies zero months/requirement/facility/fee and fixed-zero reserve policy, preventing the generic automatic reserve default from silently reactivating.
- Required reserve, actual balance and funding/release cash are distinct; existing Last Run evidence is preserved.

## Real Solar/Wind Financial Acceptance

These are controlled canonical production runs on existing synthetic references with a requested 95% cap, to exercise binding constraints. They are not calibration targets. Every case converged authoritatively, reconciled sources/uses within 1e-5 kEUR and closed Senior within the existing clean adapter's 1e-4 kEUR convergence tolerance. Tiny residuals are not overwritten with zero.

Period targets: first 10 operating periods at 1.20x, remaining debt periods at 1.45x. Each actual Bank sizing DSCR meets its corresponding target within tolerance. Base actual DSCR is separately recorded; Bank CFADS never replaces Base CFADS. Both projects use 30 real semiannual debt periods, not 30 calendar years.

Amounts below are kEUR. Interest and service are full-horizon sums of the returned canonical vectors, for test evidence only.

| Solar case | Senior | Total Uses | IDC | Structuring + arrangement | Initial DSRA | Interest | Service | Binding |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Baseline | 35,006.98 | 36,941.13 | 813.24 | 350.07 | 2,500.16 | 17,717.76 | 52,724.74 | DSCR |
| P50 lender | 35,253.07 | 37,108.49 | 816.33 | 352.53 | 2,659.51 | 16,489.36 | 51,742.43 | GEARING |
| Scalar 1.50x | 28,366.01 | 36,113.65 | 592.11 | 283.66 | 2,000.13 | 14,413.45 | 42,779.45 | DSCR |
| Period targets | 31,469.94 | 36,340.50 | 701.43 | 314.70 | 2,069.10 | 15,109.33 | 46,579.28 | DSCR |
| All-in 6.50% | 33,355.10 | 36,988.93 | 885.83 | 333.55 | 2,500.16 | 20,335.40 | 53,690.50 | DSCR |
| Gearing / level principal | 34,710.82 | 36,537.70 | 817.06 | 347.11 | 2,100.26 | 14,690.13 | 49,400.95 | GEARING |
| Fees 2% / 2% / 1% | 35,152.17 | 37,902.09 | 816.11 | 1,054.57 | 2,500.16 | 17,789.24 | 52,941.41 | DSCR |
| NONE | 32,674.41 | 34,394.11 | 819.80 | 326.74 | 0.00 | 15,131.27 | 47,805.68 | GEARING |
| Fixed cash reserve 500 | 33,159.21 | 34,904.43 | 819.15 | 331.59 | 500.00 | 15,655.72 | 48,814.92 | GEARING |
| DSRF 500 / 0.75% | 32,674.41 | 34,394.11 | 819.80 | 326.74 | 0.00 | 15,131.27 | 47,805.68 | GEARING |
| Peak 12 months | 35,376.53 | 39,387.03 | 735.96 | 353.77 | 5,000.32 | 17,899.70 | 53,276.23 | DSCR |

| Wind case | Senior | Total Uses | IDC | Structuring + arrangement | Initial DSRA | Interest | Service | Binding |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Baseline | 47,621.86 | 50,128.27 | 2,692.65 | 476.22 | 3,628.96 | 20,909.58 | 68,531.44 | GEARING |
| P50 lender | 47,517.74 | 50,018.67 | 2,692.88 | 475.18 | 3,522.06 | 18,180.11 | 65,697.85 | GEARING |
| Scalar 1.50x | 42,302.63 | 49,139.72 | 2,398.82 | 423.03 | 3,025.66 | 21,495.11 | 63,797.74 | DSCR |
| Period targets | 46,965.33 | 49,603.37 | 2,683.09 | 469.65 | 3,130.00 | 22,563.19 | 69,528.52 | DSCR |
| All-in 6.50% | 48,176.58 | 50,712.19 | 3,192.04 | 481.77 | 3,699.69 | 27,772.94 | 75,949.52 | GEARING |
| Gearing / level principal | 46,833.90 | 49,298.84 | 2,694.40 | 468.34 | 2,819.96 | 19,811.02 | 66,644.92 | GEARING |
| Fees 2% / 2% / 1% | 48,938.35 | 51,514.05 | 2,771.86 | 1,468.15 | 3,628.96 | 22,279.65 | 71,218.00 | GEARING |
| NONE | 44,087.27 | 46,407.65 | 2,700.52 | 440.87 | 0.00 | 17,518.87 | 61,606.14 | GEARING |
| Fixed cash reserve 500 | 44,574.26 | 46,920.28 | 2,699.43 | 445.74 | 500.00 | 17,964.36 | 62,538.62 | GEARING |
| DSRF 500 / 0.75% | 44,087.27 | 46,407.65 | 2,700.52 | 440.87 | 0.00 | 17,518.87 | 61,606.14 | GEARING |
| Peak 12 months | 51,294.22 | 53,993.92 | 2,684.47 | 512.94 | 7,399.37 | 24,833.88 | 76,128.10 | GEARING |

Wind P50 does not increase debt: gearing binds and the changed service profile changes required reserve/Uses. This is not treated as a bug. The 3% structuring + arrangement test reconciles exactly to committed Senior in these no-VAT-facility generic cases. DSRF total fees: Solar 51.9246575; Wind 46.2739726 kEUR, with zero initial cash reserve.

Project IRR remains 11.767978% Solar / 13.310998% Wind across these financing-only cases. The deliberately high gearing/level-principal case has Base minimum DSCR below 1 (Solar 0.803606x / Wind 0.874546x); canonical equity/sponsor IRRs are unavailable, not fabricated. Complete raw evidence includes actual Base min/average DSCR, Bank min DSCR, minimum LLCR, equity/sponsor IRRs, terminal balance and solver status in local `artifacts/f2-financial-matrix/.../*-financial-matrix.json`, regenerated by the focused matrix tests.

## Validation and Browser Evidence

- Existing focused regression ring: 299 passed, 10 existing governance-marker skips; normal process exit. No tests added to skip or removed to obtain green.
- Final F2 focused acceptance: 33 passed, zero skipped, normal process exit (284.77 seconds).
- Supplemental Goal Seek/scenario/registry/context/previous-financing ring: 172 passed, zero skipped, normal process exit (252.98 seconds). Final shared fee guard + Solar/Wind lifecycle/export recheck: 3 passed.
- Ring: prior financing bankability, H1 construction/reserve/SHL/Sources & Uses, released engine authorities, V2 persistence/governance/Run binding, F07-B export, U2.1 export and decision workspace.
- F2 focused suite covers invalid/duplicate JSON, exact typed mapping, no-config neutrality, real save/reload/Run, period targets, rates, reserves, fees, Last Run/export immutability, owner isolation, protected Save, CAS, tenor alignment, first Save after scenario selection and no GET-time solver execution.
- Python environment: 3.12.10, Windows; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids an unrelated global web3 plugin import failure. CI uses its own dependency-isolated environment.
- Authenticated Playwright: four verticals x light/dark x 1440/390px; 16 screenshots, no page errors, contrast >=4.5, period-table horizontal scrolling and collapsible controls.
- Solar/Wind browser: actual Save, reload, first-click canonical Run and subsequent STALE Save with original Last Run identity preserved; normal browser/server/model-executor teardown.
- Browser percentage proof: entering 6.50 saves a first-period typed annual rate of 0.065, followed by a real canonical Run.
- Evidence: `artifacts/model-financing-f2/evidence.json`, 16 viewport screenshots and Solar/Wind `*-stale.png`. Artifacts are intentionally untracked.
- Browser command: `python -m tests.model_financing_f2_browser_acceptance`.
- No browser-side sizing, DSCR, interest, fee, reserve or return calculations; JavaScript serializes selected inputs only.

## Explicitly Blocked / Follow-up Authority

1. Annual/quarterly clean Senior execution: current canonical adapter/PeriodEngine rejects these frequencies. No misleading alternate period editor is exposed.
2. MINIMUM_DSCR_SCULPTED and FROZEN_EXCEL_SCHEDULE as new editable sizing choices: typed modes exist but current clean project adapter rejects them. Frozen references are not promoted.
3. Fixed/floating/hedge operating modes: typed `SeniorDebtInterestConfig` helpers exist, but the clean Senior project adapter requires EXPLICIT_ALL_IN_SCHEDULE. No parallel rate engine is introduced.
4. Explicit construction pricing / VAT facility editor: existing source-owned construction contract is retained; changing these needs a separate full typed/persistence integration review. No competing manual CAPEX fee is added.
5. New dynamic reserve policies outside the existing generic automatic-peak path and fixed cash/standby DSRF: require additional targeted operating policy proof before exposure.
6. New per-scenario financing configuration: not added; grouped F2 contract is explicitly project-owned. No namespace or override semantic redesign.
7. Persisted solver binding/status audit presentation: current debt runtime projection does not expose the complete solver diagnostics contract. Existing unavailable wording is retained; no inference from requested gearing/current input is made. Tests inspect actual canonical solver diagnostics directly.
8. Existing kernel numeric guard edge: Solar Working Copy at 16 MW, P50 lender and 10-year tenor reaches `G2A_FINAL_SENIOR_DOES_NOT_MATCH_CAPACITY_MINIMUM` (expected 6617.989864516111, actual 6617.9898647462705 kEUR). The effective typed input is consumed; Run fails closed and does not publish a result. F2 does not change the guard, precision, formulas or constants to make this case pass. The same untouched financial authority requires a separately authorized numerical-convergence review. The successful tenor-change acceptance uses 12 years and 24 actual debt periods; universal tenor/configuration feasibility is not claimed.

Local full public safety scan found only the pre-existing Swagger vendor SHA exemption mismatch caused by Windows CRLF checkout. Raw base blob SHA256 `fd76294e33356ab3fd111ddaeeb10d3f79de8ae1a4d34dbf777f5eef224648d9` exactly matches the scanner's approved vendor hash; normalizing local CRLF to LF matches that base byte-for-byte. Neither vendor bytes in Git nor scanner/exemption rules are changed. Changed F2 files are separately scanned; Linux exact-head workflow remains the full safety authority.

## Review Gate

Required exact-head workflows: Governance Full History, Dependency Security Audit, Protocol UI Browser Acceptance, PR Compile and Safety Gate, Public Safety and Model Smoke. Full-suite interpreter exit and evidence upload must succeed; a `100%` pytest progress line alone is not acceptance. Live exact-head conclusions and focused final count are recorded in the Draft PR delivery body. Independent review, not deployment or merge, is the next action.
