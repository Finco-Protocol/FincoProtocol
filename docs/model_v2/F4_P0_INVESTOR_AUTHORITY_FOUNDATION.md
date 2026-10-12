# F4 / P0 Investor authority foundation

## Provenance and disposition

Audited main: `2913c90852aad0abde7265b9ffc145125ced8ac6` (verified through
GitHub and local fetch on 2026-10-12). Isolated branch:
`feat/model-f4-investor-authority-foundation`. No F3.7/Revenue branch integration.

Disposition: isolated candidate contract and equivalent common-equity adapter
are justified. Institutional preference/carry activation is **NO-GO** pending
independent financial review. This is not a released investor engine, writer,
Run payload, or export. The live Investor sheet is unchanged.

## A. Existing capability matrix

Classification refers to institutionally usable authority, not simply the
existence of a class. Utility code is not canonical production evidence.

| Capability | Status | Exact evidence and limitation |
|---|---|---|
| Investor registry/stable IDs | PARTIAL | `finco_core/sponsor/investor_registry.py:InvestorEntry/InvestorRegistry` validate IDs/duplicates but require exactly one GP; no agreement persistence/Run binding. |
| Multiple capital providers | PARTIAL | `finco_core/inputs/financing_instruments.py:CapitalProvider/FinancingCollection` and sponsor registry exist; facility provider is not investor distribution entitlement. |
| Ownership percentages | PARTIAL | `SponsorShare` in `finco_core/sponsor/sponsor_waterfall_tier.py` and registry reconcile fractions; no production investor agreement authority. |
| Dated contributions | PARTIAL | `finco_core/sponsor/capital_stack.py:CapitalContributionEntry` stores cumulative indexed amounts; F3 draws are dated funding, not dated legal-equity investor accounts. |
| Different equity classes | MISSING | F3 has `PREFERRED_EQUITY` type but rejects execution via `F3_PREFERRED_EQUITY_DEFERRED`; no executable agreement/class entitlements. |
| SHL funding | DONE | `financial_engine/financing/project.py`, `financial_engine/shl/`, `financial_engine/shareholder_waterfall/model.py:run_project_shareholder_waterfall_model` own actual funding/service and sponsor receipt streams. Multiple-investor lender attribution is still missing. |
| Preferred equity | NOT AUTHORITATIVE | `finco_core/sponsor/preferred_return_calculator.py` is an isolated accrual utility; it does not authorize preferred equity in canonical Run. |
| Preferred return accrual | NOT AUTHORITATIVE | Same utility uses indexed semiannual accrual (0.5), not general dated agreement policy. |
| Return of capital | NOT AUTHORITATIVE | `finco_core/sponsor/waterfall_runner.py:_allocate_return_of_capital` uses aggregate cumulative contributions/share allocation, not investor-specific unpaid capital reconciliation. |
| GP catch-up | NOT AUTHORITATIVE | `waterfall_runner.py` and `multi_investor_waterfall_runner.py` contain legacy assumptions described below. |
| Promote/carry | NOT AUTHORITATIVE | `waterfall_runner.py:_allocate_promote` and multi-investor runner; no immutable agreement authority. |
| Residual allocation | NOT AUTHORITATIVE | `waterfall_runner.py:_allocate_residual` is reusable proportional allocation; production does not call it for investor distribution. |
| Investor IRR/MOIC | PARTIAL | `finco_core/sponsor/sponsor_irr_runner.py:run_sponsor_irr/run_sponsor_moic` operate on sponsor accounts; IRR derives dates with `period_index * 183` days. Not arbitrary agreement cash dates or persisted investor results. |
| Canonical sponsor distributable cash | DONE | `financial_engine/shareholder_waterfall/model.py` and `contracts.py:CovenantGatedWaterfallPeriod` own final distribution gate/accounting cap/WHT and actual receipts; `net_dividend_received_keur` is the net-equity receipt boundary, not CFADS. |
| Investor-level Run evidence | MISSING | `app/workbook/runtime_result.py` and `app/persistence/run_history_repository.py` retain aggregate `sponsor_schedule`, not agreement-bound investor distributions/metrics. |
| Immutable investor export | MISSING | `app/services/v2_export_service.py` binds existing historical/Last Run output; `app/sponsor_waterfall_excel_export.py` can format isolated utility results but is not a canonical investor ledger. |

### Evidence against blanket reuse

`domain/sponsor/*` are compatibility shims importing `finco_core/sponsor/*`,
not independent financial authority. `app/sponsor_runner.py` is explicitly
internal orchestration without persistence; `app/sponsor_project_adapter.py`
uses legacy `app.ui_runner._run_waterfall`, not the clean production route.
Searches found no V2 production caller of `run_multi_investor_waterfall`.

The multi-investor runner looks up `registry.investor_for("LP-1")` and chooses
the GP from IDs not equal to `"LP-1"`, despite the registry having typed roles.
It computes each preference separately with zero distributions and then excludes
PREFERRED_RETURN from the aggregate cash cascade. The core GP catch-up branch
defaults its promote rate to 0.20 when its 100%-GP tier supplies no fractional
share. Thus explicit global carry terms are not reliably propagated there.
These are source-code observations, not claims of an affected canonical Run.
No protected code is corrected here.

## B. Canonical integration and metric definitions

Future direction, **not implemented**:

`ProjectInputs + scenario identity -> canonical production Run -> Senior ->
Junior where authorized -> reserves/covenant distribution-account gates -> SHL
actual service -> accounting dividend cap and WHT -> immutable net legal-equity
receipts -> reviewed investor agreement -> investor allocations -> investor
dated cash flows/returns -> immutable Run History -> historical export`.

Reserve/gate details remain owned by the existing canonical waterfall; this
diagram does not authorize replacing its actual order with a new adapter.

| Concept | Boundary |
|---|---|
| Project cash/Project IRR | Existing `financial_engine/project_returns/model.py` unlevered project definition, financing-independent. |
| Senior service | Canonical Senior/F3 funded facility schedule, never an equity allocation. |
| Junior service | Reviewed F3.5 amount/schedule authority; app activation still disabled. |
| SHL service | Actual paid interest/principal, separate from legal equity; PIK is not a cash receipt. |
| Cash for equity | Final net legal-equity receipts; not raw CFADS, bank case cash, pre-SHL release, total sponsor receipts, or gross dividend before WHT. |
| Preferred/common entitlement | Explicit agreement right; none is inferred from contribution size or project defaults. |
| Investor cash flows | Actual dated investor contributions and allocations, with separately attributed SHL only under a future approved contract. |
| Pure Equity IRR/MOIC | Existing aggregate legal-equity cash stream and denominator only. |
| Total Sponsor IRR/MOIC | Existing equity plus actual SHL contributions/receipts. |
| Investor IRR/MOIC | Future investor-specific dated receipts/contributions; not ownership-scaled aggregate IRR. |

`app/services/clean_presentation_adapter.py:build_clean_sponsor_schedule`
passes canonical aggregate values through. Its current period payload exposes
`legal_equity_distribution_keur`; it does not expose every net dividend/WHT
field needed for future investor tax allocation. F4 must obtain reviewed net
evidence, not infer net from that legacy-shaped payload. The live Investor sheet
explicitly says no supported Investor write contract exists yet.

## C. F3 -> F4 boundary

F3 owns instrument identity, lender/provider references, commitments, dated
funding, interest, maturity, actual payment, liability and Sources & Uses.
F4 owns agreement identity, legal classes, explicit equity entitlements and
allocation of cash already released by the canonical engine.

F4 must not resize debt, pay Junior/SHL a second time, reuse gross sponsor receipts
as equity cash, manufacture an unfunded preferred payment, or alter unlevered
Project IRR. F3.5 `app/workbook/junior_debt_config.py:ACTIVATION_ENABLED=False`
remains unchanged. F3.6 proposal UI is not proof of Junior runtime activation.

## D. Candidate schema (version 1)

Location: `app/model_v2/investor_f4_candidate/` only.

`InvestorAgreement` contains explicit agreement reference, typed investor tuple,
dated contribution tuple, explicit priority declarations/contractual terms and
`DistributionEvidence`. Each investor carries a stable ID, investment class,
ownership fraction and commitment. Contributions carry investor ID, exact cash
date and nonnegative finite kEUR. Equity ownership totals one within the existing
tier 1e-8 tolerance; SHL ownership must be zero. Contributions cannot exceed
commitment within the existing result 1e-6 kEUR tolerance.

Cash dates must be explicit and strictly increasing. Contribution dates must
occur on that axis: there is no implicit date bucketing/year assumption. An
uncalled commitment need not be represented as cash. Caller-supplied evidence
references are **not** verified Run IDs, authorization grants or freshness
claims. A future authorized immutable Run binding is a separate approval gate.

Schema v1 supports only **COMMON_EQUITY + explicit RESIDUAL-only priority** for
offline execution. Preferred/SHL classes and ROC/preference/catch-up/promote
declarations are classified unsupported and rejected by the adapter. An explicit
preferred rate/carry fraction is required for its declared tier, but supplying
it does not activate the right. No 8%/20% default exists. Canonical JSON sorts
investors/contributions and fields; SHA256 binds the entire candidate content,
including dates, cash and evidence reference. No storage/parser/write endpoint
is introduced.

## E. Reuse/function map

| New function | Closest existing implementation | Why narrowly needed |
|---|---|---|
| Candidate dataclass validation | `InvestorEntry/InvestorRegistry`, `CapitalContributionEntry`, `SponsorWaterfallTier` | One/two common investors without fabricated GP role; explicit dates/classes and rejection of unsupported entitlement semantics. No financial allocation logic. |
| `unsupported_reasons` | F3 instrument validation and tier enums | Separate declaration from candidate executability; no silent fallback to 8-and-20. |
| `to_json/content_digest` | F3 deterministic typed serialization | Bind isolated agreement and evidence; no Run hash replacement. |
| `to_existing_inputs` | `WaterfallRunnerInputs`/`SponsorShare`/`SponsorWaterfallTier` | Pure date-to-cumulative contribution projection and RESIDUAL mapping; no new distribution formula. |
| `evaluate_candidate` | `finco_core/sponsor/waterfall_runner.py:run_waterfall` | Calls that exact existing runner once; does not call the legacy multi-investor carry runner. |
| `validate_candidate_result` | `PeriodWaterfallResult/TierAllocationEntry` reconciliation | Check delegated cash/identity against original receipt, reject over-allocation and unauthorized retention. No repair or allocation recomputation. Not a verifier of arbitrary agreement economic performance. |

No candidate IRR/MOIC, preferred accrual, ROC accounting or second waterfall
engine is implemented. Residual distributions are not relabelled ROC/pref.

## F. Cash contract and missing approvals

For every candidate period: supplied net cash = sum investor distributions;
retained cash = zero because this candidate has no retained-cash authorization.
Contributions are funding evidence, not new distributable cash. No automatic
transfer of unallocated entitlement or residual balancing plug is allowed.
ROC and preferred balances require future investor-specific capital accounts,
dated accrual/compounding, priority/catch-up semantics and independent oracles.

Before production: independently approve agreement policy/content, authorized
writer/CAS/scenario composition, immutable investor identity and evidence schema,
net/gross/WHT attribution, canonical maturity/unpaid-debt gates, Run serialization,
historical export, investor dated XIRR/MOIC and engine governance paths. Activation
and UI require separate approval. Existing aggregate return definitions stay intact.

## G. Acceptance evidence

`tests/test_investor_f4_candidate.py` covers one/two common investors, exact core
delegation, identity/ownership/contribution/date/rate validation, unsupported
rights, SHL separation, over-allocation/retention/nonfinite result rejection,
immutable deterministic serialization, no production imports and real canonical
net dividend receipt delegation without mutation of the clean result.

Local acceptance: 43 new candidate tests pass. The combined candidate, H3,
U2.2 Returns, canonical F3 legacy, two-Senior, F3.5 governance, Model V2 released
authority and financial-integrity ring passes **239 tests, zero failures, rc=0**
with normal process termination. Python 3.12.10; external plugin autoload disabled.
The sandboxed TestClient attempt was interrupted and rerun outside the localhost
sandbox with disposable test storage. No tests or assertions were skipped/changed
to accommodate that environment.

All six whole-result fingerprints below were recaptured after implementation and
match their before values exactly. Evidence files are outside Git. No golden changes.
Compilation/diff hygiene and the targeted five-file safety scan pass.
The full Windows safety scan reports only the pre-existing Swagger bundle
CRLF checkout mismatch: Git source SHA256 is the approved
`fd76294e33356ab3fd111ddaeeb10d3f79de8ae1a4d34dbf777f5eef224648d9`;
normalizing working CRLF to LF reproduces those source bytes exactly. There is
zero vendor diff. No vendor/guard change is authorized or made. Full Linux safety
and exact-head CI remain required; their actual results belong in the Draft PR
description, not a presumed success in this pre-push document.

### Current baseline whole-result SHA256

| Case | SHA256 |
|---|---|
| Solar | `a24ac63a228a63e9ddecf6c2f7bbe094d4633f56edc0cdb9c6c5f1af92e0f481` |
| Wind | `b8f2dee7eaa64272f209a9e554e64bfb06d3f702d7d08151060ac0e93c696333` |
| Data Center | `bfbdd3d64bfccb36242fe5a78172e24d9f9dcb03e98c375629b729a738217bed` |
| EV | `45b428a84725864fb39e6d15f37c2a0b79c85ac5081b2e8c0192e3e704e4f545` |
| Two-Senior Solar | `5f101488ed30e6364b75274a921b96bcbb71f1377aa185271919ebbdb9a2b42d` |
| Two-Senior Wind | `06af88ed77a019844e4a218e9a180b905560c4ffba0768e3645ff9e5dbc02265` |

Frozen namespaces, router, live Investor sheet, Run/CAS, persistence, export,
governance helper and workflows have zero diff from the audited main.
