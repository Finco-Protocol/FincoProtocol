# F3.8 Institutional Financing Integration V1

## Provenance and boundaries

Base: `86792f12ac9ad6763df0881538e682b0d40ed8bb`.
Dependencies #253, #255, #257, #258 and #259 are merged.
Dedicated branch: `feat/model-f38-financial-integration`.
Delivery is one Draft PR; no approval, merge or deployment.

ZERO modifications to `financial_engine/`, `finco_core/`, `domain/`,
`tests/model_v2_governance.py`, existing release maps, tolerances and goldens.
Junior production activation remains `False`. Junior coverage uses the existing
explicitly enabled synthetic test fixture, never an application enablement.

## Existing authorities reused

| Capability | Existing source | Assessment |
| --- | --- | --- |
| Funding, commitments, IDC and fees | F1/F3.7 persisted financing evidence and `build_sources_uses_projection` | DONE; reused with exact Run/scenario binding |
| Two-Senior contractual schedules | `facility_schedules` | DONE; no second solver |
| Controlled Senior + Junior schedules | `senior_facility`, `junior_facility`, `junior_cash_idc` | DONE; inert production boundary preserved |
| Statements and accounting | WF-06 `RuntimeResult.financial_statements` | DONE; presentation-only, persisted 2dp |
| Tax schedule | `RuntimeResult.tax_schedule` | PARTIAL: aggregate audit fields, not facility deductions |
| Sponsor/Project metrics | Existing `build_returns_projection` | DONE; no new IRR |
| Full-precision cash and BS audit | Persisted Run Integrity evidence/checks | DONE; existing evidence digest and BS check reused |
| Facility tax attribution | No persisted authority | NOT AUTHORITATIVE; explicitly UNAVAILABLE |
| Investor-specific economics | Separate F4 candidate | Outside F3.8; not activated or inferred |

## Functional integration

An expandable read-only trace appears in existing Statements & Debt, Tax and
Returns. It loads `/v2/workbook/financing/trace` on expansion. There are no new
navigation destinations, editable controls or browser financial calculations.

The route captures one authorized `PostRunRequestContext`, requires its
owner/project scope, uses the canonical Run History repository for historical
selection, and validates coherence after rendering. A concurrent workspace edit
or scenario selection fails closed. No Save, Run, CAS or export writer changes.

CURRENT and STALE belong to the canonical freshness authority. Historical
selection is always HISTORICAL, never promoted CURRENT. Selected history names,
snapshot/hash, timestamp and financial payload come from the immutable owned
entry, not current Working inputs. A historical navigation list may grow; the
selected historical financial content must not change after a later Run.

## Reconciliation matrix

| Binding | Evidence | Check / unsupported boundary |
| --- | --- | --- |
| Commitment vs actual draws | F3.7 validated construction ledgers | Commitment is not shown as cash drawn |
| IDC / fees -> Project Uses | Existing F3.7 checks and native construction rows | Senior IDC and Junior cash IDC retain separate homes |
| Funded opening | Sum of actual draws vs first operating opening | Full precision, existing 1e-6 kEUR audit tolerance |
| Facility roll-forward | Opening, principal, closing; consecutive openings | Full precision; missing/duplicate/gapped vectors rejected |
| Facility debt service | Interest + principal vs actual service | Full precision; no repaired values |
| Instrument -> P&L | Senior sum / separate Junior interest | Existing persisted 2dp serialization, not a new tolerance |
| Instrument -> BS | Senior sum / separate Junior closing balance | Same persisted 2dp binding |
| Instrument -> PF | Senior sum / separate Junior debt service | Same persisted 2dp binding; Senior never relabelled total debt |
| Instrument -> Integrity | Senior and Junior operating vectors | Full precision cross-check to independent persisted audit |
| CFADS -> post-Senior | Integrity Base CFADS minus Senior service vs audit cash | Bank CFADS is never substituted |
| Post-Senior -> post-Junior | Integrity Junior cash seam | Actual service, no financing plug |
| BS Assets = Liabilities + Equity | Existing `check_balance_sheet` | Separate PASS/FAIL/UNAVAILABLE; original tolerance untouched |
| Sponsor cash | Native Integrity cash events | Construction and operating grains remain separate |
| Tax | Depreciation, before/after-loss income, loss opening/use/close, CIT accrual and cash tax | Existing persisted aggregate evidence, no tax allocation |
| Returns | Project / Pure Equity / Total Sponsor IRR plus actual SHL cash | Existing metrics and audit events, no investor IRR derivation |

The trace badge concerns evidenced financing/cash bindings, NOT complete tax
attribution or a replacement financial Integrity verdict. DIFFERS outranks
UNAVAILABLE; incomplete numbers cannot be replaced with zero. A missing legacy
facility split remains UNAVAILABLE while actual aggregate cash/returns remain
visible. Actual maturity balances are retained exactly, including sub-display
residuals; no rounded positive balance is labelled REPAID.

Statement comparisons round the instrument sum using the exact existing
`round(value, 2)` serializer boundary, then compare with the existing full-precision
audit tolerance. This proves display/export binding only. Separate full-precision
facility/Integrity identities prevent display rounding from concealing debt drift.

## Exact unsupported items / future exposure proposal

1. No per-facility deductible interest, allocated corporate tax, or tax savings
   is persisted. Do not proportionally allocate aggregate tax.
2. Historical TaxPolicy / interest-limitation configuration and full-precision
   annual tax bridge are not part of this persisted presentation payload.
3. The funded IDC ledger proves financing costs, not an independently persisted
   asset-component depreciation allocation. No synthetic useful life is inferred.
4. Legacy/single-Senior Runs do not expose separate facility commitments/draws/
   maturities. No split is reconstructed from Working inputs.
5. Investor-specific return allocation remains F4; Junior activation is closed.

Potential follow-up: reviewed read-only commit-time exposure in
`app/api/project_runner.py` of existing `FinancialStatementsResult.tax_bridge_periods`,
accounting-policy/book-component provenance, and effective TaxPolicy evidence.
This would require separate schema/lineage/export contract review for historical
absence. It is NOT implemented here and does not justify modifying any protected
financial formula or pin. Per-instrument tax attribution must remain unavailable
unless a canonical financial authority actually owns it.

## Canonical parity

Before and after complete canonical clean-result fingerprints are identical:

| Fixture | SHA256 |
| --- | --- |
| Generic Solar | `a24ac63a228a63e9ddecf6c2f7bbe094d4633f56edc0cdb9c6c5f1af92e0f481` |
| Generic Wind | `b8f2dee7eaa64272f209a9e554e64bfb06d3f702d7d08151060ac0e93c696333` |
| Data Center | `bfbdd3d64bfccb36242fe5a78172e24d9f9dcb03e98c375629b729a738217bed` |
| EV | `45b428a84725864fb39e6d15f37c2a0b79c85ac5081b2e8c0192e3e704e4f545` |
| Two-Senior Solar | `5f101488ed30e6364b75274a921b96bcbb71f1377aa185271919ebbdb9a2b42d` |
| Two-Senior Wind | `06af88ed77a019844e4a218e9a180b905560c4ffba0768e3645ff9e5dbc02265` |

No recalibration, golden refresh or numerical tolerance change. XLSX tests bind
the same persisted statement cells and dated columns, excluding the export's
separate Total column; export-time engine execution is forbidden by the test.
Existing WF-06 XLSX four-vertical and facility tests remain in the regression ring.

## Acceptance and evidence

New tests: `tests/test_financing_f38_trace.py` and
`tests/test_financing_f38_browser.py`. Coverage includes canonical Solar/Wind
two-Senior and controlled Junior, four inactive verticals, malformed vectors,
statement/date/binding tampering, Integrity digest, actual maturity, cash/tax/return
sources, NOT_RUN/CURRENT/STALE/HISTORICAL, historical immutability, owner/project
isolation, coherence failure, no GET/export engine execution, XLSX and accessibility.

Chromium traverses actual workbook Statements & Debt, Tax and Returns, opens the
trace and facilities, checks statuses, captions, keyboard-scroll regions, no page
errors, and no horizontal page overflow at 1440px light and 390px dark.
Screenshot evidence is outside Git: `f38-browser-evidence/solar-light-1440.png`,
`solar-dark-390.png`, `wind-light-1440.png`, `wind-dark-390.png`.
Binary artifacts are not committed.

Local acceptance: broader regression ring 431 passed; final F3.8 focused checkpoint
35 passed (including three Chromium cases), then both Senior/Junior XLSX cases
passed after adding the Junior export parameter. The final F3.8 inventory is 36
tests; these are overlapping checkpoints, not additive unique-test claims.
Exact committed-head focused execution subsequently passed all 36 tests in
214.64s with rc=0, including three real Chromium cases.
Existing WF-06 standalone acceptance: 44 passed. All completed processes exited
normally with pytest rc=0. Compilation, changed-source safety and diff hygiene
passed. Six canonical before/after fingerprints above are identical.

Exact-head five workflow results are recorded in the Draft PR delivery/evidence.
Require full unsharded Public Safety, pytest/supervisor exit 0,
mandatory uploads, tested merge-tree equality and six browser roles. No CI changes.
Local Windows full source scan may encounter the existing CRLF vendor-byte
exception mismatch; changed-source safety and Linux exact-head CI are separate
evidence, never a scanner exception added by this PR.

Initial exact-head CI found a test collection error: Public Safety intentionally
does not install Playwright. The new browser test imported Playwright before the
existing F3.7 browser fixture's optional-dependency boundary. The correction only
orders that existing fixture import first; no assertion, financial code,
dependency or CI change. Real local Chromium acceptance remains required and
separate from the six mandatory browser roles. Fresh exact-head CI must complete
after this test-only correction; the initial failed run is not acceptance.

Recommended disposition: independent review of supported read-only integration;
no claim of completed facility tax allocation or released Junior activation.
