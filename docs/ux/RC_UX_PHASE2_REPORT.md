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


---
## Continuation B (this commit) - status: PARTIAL, remaining work documented

### Delivered
- **Scheduled PPA flow**: the guided form fills an explicit price for every operating period (the price the user typed, never invented), opens and focuses the existing price-point editor, shows "Incomplete draft" and keeps Save disabled while any point lacks a date or price; entered fields survive validation errors. The old toolbar is relabelled "Other contract types" so there is one obvious Add PPA entry point; expert tools stay available.
- **Navigation hierarchy** (presentation only, area IDs and tab IDs unchanged except the new `financing` area): Inputs, Financing, Results, Scenarios, Analysis, Model Checks, Trust. Senior debt and Investors moved from Inputs to Financing; Outputs is labelled Results. Pins updated in `test_model_workspace_consolidation.py`, `test_model_v2_ux_shell.py`, `test_workflow_c_statements_analytics_trace.py`, the hybrid-nav browser test and the keyboard-navigation test (Inputs -> Financing is now the next area).
- **Debt / Equity copy**: "Not supported by the engine" -> "Not available in this release"; saved financing proposals are stated to change neither the model nor the next Run until activation is released; the Investor panel now separates ownership % (allocates results, does not change Sources & Uses) from commitments and paid-in capital (funding, must reconcile before Run). Junior and F4/P2 remain release-closed and unchanged.
- **Run History (UX-024)**: wide tables scroll inside their own region; before this change the Run History page overflowed the document at 1440 and 1366 px (1551 px wide table).
- **Test-helper defect fixed**: waits for the saved state used a case-insensitive substring ("Unsaved changes" matched "Saved"), which could let a test click Run before Save finished and hit the stale-draft refusal.
- **Test assertion refined (needs reviewer attention)**: `test_four_consecutive_edits_save_atomically_with_stable_focus_and_scroll` measured `scrollY`. With the new layout, browser scroll anchoring moves `scrollY` by 25 px when the unsaved-edits row collapses, while the edited cell does not move. The test now asserts that the edited cell stays within 2 px and that `scrollY` moves at most by the document-height change. Reverting the navigation change restores the old behaviour.

### Evidence
- `tests/test_rcux2_ppa_quick_add_browser.py`: 10 cases pass under the real CSP (Quick Add Save; two PPAs; indexed; invalid inputs; 390 px dark; Scheduled PPA incomplete-draft -> Save -> Run; Fixed then Indexed -> Save -> Run with earlier Run History entries unchanged).
- Debt/Equity browser acceptance reuses the existing suites `test_capital_stack_workspace_browser_v1.py` and `test_investor_f4_browser.py` (passed in the same run as 64 tests; the two failures of that run are described above and were fixed).
- Before/after screenshots (5 screens x 4 viewports, `main` vs this branch) and `perf-before.json` / `perf-after.json` were captured locally under `artifacts/rcux2-screens/` (git-ignored). At 1440x900 light, page load was within noise (about 2.8-3.2 s locally for both; first response 0.9-2.3 s, dominated by server rendering, not CSS). Local Chromium only, not staging.
- Run History overflow remains verified only for the new wrapper by inspection plus the existing run-history suites (their full run was still in progress when this commit was made).

### Not done
- Journeys not yet automated end to end: multiple PPAs with residual Merchant, scenario change and restoration of contracts, add Senior debt -> Save -> Run (activation is release-closed, so the journey ends at SAVED PROPOSAL), investor allocations -> Run (existing suite covers it).
- Compact Overview / header duplication, Flowbite/Tailwind (optional), remaining UX findings UX-009/010/011/012/015/016/021-023/025/026/028/030, mobile financial-table pass, Trust / Diagnostics wording (proposal table pending owner approval: "Trust" area label and tab text, Diagnostics heading "Model Diagnostics" -> "Model Checks").
- Exact-head CI and independent review.
