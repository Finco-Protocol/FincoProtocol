# FINCO F4/P2 — Advanced Legal Investor Waterfall: proposed policy / release-closed

**Financial/legal-policy disposition: NOT AUTHORIZED.** This is a *candidate financial model*, not a substitute for executed shareholder agreements. Independent financial and qualified legal-policy review is required. No existing P1 Save/Run/Run History/export or route calls the candidate. Schema `2` is neither a migration of nor a valid input for P1 schema `1`.

Baseline examined read-only: `cff1a7b19a72429636ec20325aadf5364365b12d` (2026-10-13); actual GitHub main must be rechecked before commit and review. P0: `docs/model_v2/F4_P0_INVESTOR_AUTHORITY_FOUNDATION.md`. P1: `docs/model_v2/F4_P1_INVESTOR_WATERFALL_REPORT.md`. F3.8: `docs/model_v2/F3_8_FINANCIAL_INTEGRATION_REPORT.md`.

## 1. Existing legal and finance boundary

Canonical G2C `CovenantGatedWaterfallResult.waterfall_periods` already owns bank debt, SHL service, reserves, covenants, accounting dividend cap, and WHT. P1 `app/model_v2/investor_f4.py` reconciles **net legal-equity receipts** and actual four-field paid-in legal equity funding, with exact dates and agreement/project/scenario binding. P1 distributes common-equity residual across explicit ownership fractions, computes dated XIRR with existing robust_xirr, stores immutable `investor_waterfall_v1` Last Run / History and emits a run-bound export. It does **not** categorize residual as return of capital. P0 `investor_f4_candidate` explicitly rejects preferred economics. Existing `finco_core.sponsor.multi_investor_waterfall_runner` must NOT be reused as binding P2 policy because GP/LP IDs and carry defaults are not authorized. F3.8 adds read-only financing trace, not investor legal allocations. F3.5-B / Junior activation remains separate.

**P2 candidate source boundary:** one caller-supplied P1-form `schema_version=1` receipt dict with source exactly `CovenantGatedWaterfallResult.net_dividend_received_keur`, net equity receipts plus gross/WHT for consistency and exact dated contributions; a typed explicit binding (owner, project, scenario, snapshot, composite hash). *The offline candidate cannot attest that those caller-supplied values are genuinely from a committed FINCO Run.* It always reports `source_attestation=UNVERIFIED_OFFLINE_CALLER_INPUT`, `run_history_binding=NOT_COMMITTED`, `production_export=BLOCKED`.

## 2. Legal/economic policy decision matrix — all proposed, NOT approved

| Decision | Proposed narrow offline behavior | Approval / alternative required before activation |
|---|---|---|
| Agreement identity/version | Schema `2`; exact IDs, legal owner/project/scenario/run binding; immutable canonical JSON SHA-256 | Signed agreement, amendments, effective dates, governing law |
| Equity class definition | Explicit class IDs and holders; no inferred GP/LP, loans or preferred status | Rights, transfer clauses, class-specific rights |
| Cash source | Actual P1/G2C **net legal-equity cash only**; reject CFADS, gross dividends and debt receipts | Confirmation of upstream legal WHT and distribution authority |
| Legal equity funding | Dated actual contributions, matched by exact date to P1/G2C funding within pre-existing P1 `1e-6` kEUR reconciliation | Whether interim subscriptions/escrow/capital calls change cash date |
| Tier ordering | Contract **ordered** list; no universal order; `RESIDUAL` exactly once, last | Negotiated priority schedule for every class |
| Return of capital | Pay unpaid actual contributed principal to the explicitly nominated class, capped by account balance; simultaneous holders pro-rata by outstanding amount | Paid-in categories eligible for ROC, priority vs preference |
| Preference method | **Proposed** simple noncompounding annual preference on unreturned paid-in capital only | Simple / compound / IRR hurdle / investor ledger basis |
| Day count | **Proposed** ACT/365 Fixed, using exact calendar days | ACT/360, 30/360, leap-year convention and timezone |
| Preference start/stop | Proposed: each contribution date to each ROC payment date; contributions on same event earn from following interval | Distribution ordering, capitalization, crystallization |
| Partial ROC | Reduces future accrual principal; does not retroactively erase unpaid preference | Whether preference continues on returned money |
| Cash shortfall | Carry unpaid principal/preference with original priority to later dates; never invent cash | Arrears, compounding on arrears, clawback remedies |
| Hurdle testing | **Proposed** cumulative unpaid simple preference; no IRR-based hurdle | Whether hurdle periodic/cumulative/IRR and catch-up trigger |
| Catch-up | Only explicit beneficiary and positive **lifetime nominal cap**; pays up to cap when its listed stage is reached | Negotiated formula for GP catch-up; no default GP 100% or 20% |
| Carry/promote | Only explicit beneficiary and fraction strictly (0,1) of *cash remaining when its listed stage is reached*; balance proceeds to next tier | Actual profit-base mechanics, clawback and netting |
| Residual | Explicit ownership fractions sum exactly to 1; all named legal investors included | Class-specific residual ratios beyond overall ownership |
| Class seniority | Solely determined by explicit stage order, not class name; same-stage class holders pro-rata by unpaid entitlement | Signed priority clause and seniority conflicts |
| Reinvestment | New **actual** dated paid-in contribution is supported, not automatic reinvestment of paid distributions | Recycling, recallable distributions, deemed contributions |
| Negative distribution | **Reject** (never silently floor a negative net receipt) | Reversal, clawback, refunds and negative ledger treatment |
| Unapproved/contradictory fields | Fail closed with stable `P2_*` error; no policy defaults and no production write | Written instruction and independently reviewed implementation |
| XIRR | Existing `finco_core.sponsor.xirr.robust_xirr` when actually in FINCO checkout; independent Decimal method in synthetic tests only | Review of multiple-root convention and undefined cases |
| MOIC/DPI | Realized cash distributed / actual paid-in; **not** NAV, TVPI or unrealized gain | Separate valuation authority if requested |
| Individual investor tax/SHL | **Unsupported**; WHT is upstream legal dividend net; no SHL reallocations | Tax treaties, entity domicile, interest ownership separately reviewed |
| Production Save/Run/History/export | **Closed**; no flag, route, writer or UI integration | Separate exact-content financial authorization and evidence version review |

There is no general market-standard default. Every proposed enum in the version-2 candidate schema must be supplied explicitly and is *still only a proposal*. Other policies are rejected, not implicitly equated.

## 3. Candidate module and scope

- `app/model_v2/investor_f4_candidate/p2_contracts.py`: frozen typed investor/class/contribution/tier contract, strict bounded schema, duplicate-key and nonfinite rejection, SHA-256.
- `app/model_v2/investor_f4_candidate/p2_evaluator.py`: isolated Decimal accrual and sequential stage allocation; individual capital/pref/catch-up/carry accounts, stage trace, cash conservation, dated XIRR adapter; release-closed digest-bearing candidate projection and validation.
- `tests/test_investor_f4_p2_candidate.py`: synthetic positive, negative and independent numerical cases; expected-value bridge.
- **No edits to** `financial_engine/`, `finco_core/`, `domain/`, P1 agreement persistence, existing router/templates, Revenue, Diagnostics, Radar, F3.5-B or governance pins.

Potential production integration would require *another explicitly approved financial-authority change*: authorization of signed terms and source identity; scenario CAS and owner/CSRF; canonical run-evidence schema and atomic commit; immutable historical interpretation; export validation; investor UI with explicit legal warnings. None is implemented in this Draft.

## 4. Independently derived example, in kEUR

### Common-equity / Return of Capital first

- Actual dated contributions: A = 60, B = 40 (2030-01-01); legal residual ownership A = 70%, B = 30%.
- Canonical-like synthetic net equity receipts: 2031-01-01 = 50; 2032-01-01 = 100.
- Return of Capital tier totals = A 60, B 40. Then 50 residual = A 35, B 15.
- **Totals: A 95, B 55, allocated = 150, input net cash = 150, residual = 0.**
- If agreement is P1 RESIDUAL_ONLY instead: same 150 would allocate A 105, B 45, with ROC=0. P2 never rewrites that P1 definition.

### Multiple legal classes / Preference + Catch-up + Carry

- Classes P (A) and C (B). Each contributes 100 on 2030-01-01; each has 50% residual ownership.
- P proposed 10% simple ACT/365 preference. Ordered tiers: P ROC, P preference, C ROC, B catch-up lifetime cap 10, B carry 20% of available at that tier, residual all investors pro-rata.
- At 2031-01-01, net cash 150: A ROC 100, A preference 10, B ROC 40. No other cash available.
- At 2032-01-01, net cash 200: B ROC remaining 60, B catch-up 10, B carry 26 (20% of 130), residual 104 => A 52, B 52.
- **A total = 162; B total = 188; total = 350; canonical-like receipts = 350; exact cash residual = 0.**

These are *synthetic* reconciliations, not observed FINCO canonical Runs, executed agreements or independent legal-policy approvals.

## 5. Independent acceptance and release gate

Local isolation can prove Python compilation and the synthetic Decimal oracle. It cannot prove active application CI, canonical F4/P1 parity, tenant/CSRF/CAS, scenario switching, or immutable Last Run/export without a real, complete FINCO checkout and workflow runs. A passing Draft PR CI does not confer legal-financial authority.

Mandatory before merge: exact-head GitHub full Public Safety and mandatory evidence, Governance Full History, Dependency Security, PR Compile/Safety, six Browser roles; independent code/financial review, full original F4/P1 tests and conflict-free normal merge. Mandatory before **activating** P2: separately reviewed signed waterfall policy, independent full numerical bridge on actual Solar/Wind canonical net-equity receipts, atomic Run/History/export version acceptance, owner/CSRF/CAS route tests, historical immutability and legal review. Staging pending; no deploy authorized.
