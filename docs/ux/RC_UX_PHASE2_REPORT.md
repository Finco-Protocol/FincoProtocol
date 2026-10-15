# RC-UX Phase 2 - progress report (branch `feat/model-rcux2-institutional-workspace`)

Base: `origin/main` `03e2b9638e9324bb18ea8420ce8f9823f4f0a676` (PR #286 merged, contains `962fc9d`). Protected financial paths (`financial_engine/`, `finco_core/`, `domain/`) are unchanged.

## Preflight
- PR #286 merged; post-merge main: source-safety, protocol-verification, dependency-audit green; `safety-and-smoke / tests` was still running when checked.
- No open WF-A / other Model PR overlaps (only Dependabot and the unrelated yield PR #184).

## Ownership (this pass: one coordinator)
| Area | Files |
|---|---|
| B - Revenue / PPA Quick Add | `app/templates/v2/partials/revenue_contracts.html`, `static/js/model_revenue_contract_editor.js`, `static/css/model_revenue_contract_editor.css`, `_build_revenue_contract_editor` (read-only operating window) |
| A - copy | `_model_smart_panel.html`, `sheet_returns.html`, `sheet_revenue.html`, `revenue_contracts.html` |
| Not touched | Trust sheet wording, diagnostics, `workspace_destinations.py`, financing/investor templates |

## Delivered
- **PPA Quick Add** (guided "Add a PPA"): pricing type (Fixed / Indexed / Scheduled), starting price, contracted production %, start/end date pre-filled from the project's own operating periods, indexation for Indexed, generated stable IDs (`ppa-1`, `ppa-2`, ...). The contract reference is still required and is never invented; the existing writer, CSRF, composite CAS, scenario scope and Save/Run separation are reused unchanged. Illustrative prices without a contract use the existing PPA terms under Revenue inputs (Working PPA assumption); the form says so.
- Strict amount syntax in the form (`62,5` is refused), actionable messages, nothing added on invalid input.
- Copy: "Workbook and Trust Pack findings" -> "Model Checks"; default "No rejected edits in this session" removed; "Canonical ..." wording removed from the Revenue, Returns and contract editor; implementation commentary removed from the Smart Panel intro lines. Warnings and disclaimers kept ("not a bankability certification").

## Tests
- `tests/test_rcux2_ppa_quick_add_browser.py` (real Chromium, real CSP, no bypass): 8 cases pass - generated ID + Save + persisted stream, two PPAs, indexed PPA, five invalid inputs, 390 px dark without document overflow.
- Existing revenue-related suites: 270 passed, 1 skipped. Copy-related suites: 365 passed, 1 skipped.

## Capability matrix (revenue parity readiness; no engine change proposed here)
| Capability | Status |
|---|---|
| Fixed price, indexed price, scheduled price points | SUPPORTED DIRECTLY (contract editor) |
| Residual Merchant / contracted share | SUPPORTED DIRECTLY |
| Indexation basis | SUPPORTED WITH CONFIGURATION (operating-year basis only) |
| Term relative to COD | SUPPORTED WITH CONFIGURATION (dates default to the operating window; no "years from COD" field in the contract schema) |
| Step pricing | SUPPORTED WITH CONFIGURATION (scheduled price points) |
| Price base year, partial indexation share | MISSING / REQUIRES FINANCIAL AUTHORIZATION |
| Market-linked pricing, contracted volume limits | REQUIRES FINANCIAL AUTHORIZATION |
| P50/P90 lender pricing | REQUIRES FINANCIAL AUTHORIZATION (Commercial / Bank-case comparison exists, read-only) |
| Optional or draft-persisted `source_ref` | REQUIRES FINANCIAL AUTHORIZATION (schema change; not done) |

## Not done in this pass (honest list)
- Navigation hierarchy (A2), compact layout (A3), Flowbite/Tailwind (A4, optional), deferred findings UX-006/009/010/011/012/015/027 and UX-016/021-026/028/030.
- Debt / Equity end-to-end journeys (C1-C3), Run History usability, journeys 1-12 beyond Quick Add, before/after screenshots, performance measurement, full copy audit matrix.
- Trust / methodology wording: requires explicit owner review.
