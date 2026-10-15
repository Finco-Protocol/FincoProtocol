# RC-UX Phase 2 - final report (branch `feat/model-rcux2-institutional-workspace`)

Base: `origin/main` `03e2b9638e9324bb18ea8420ce8f9823f4f0a676` (PR #286 merged). PR #287 (WF-A numerical and credit validation) is **merged**; this branch contains `main` `38018e9` through the normal merge commit `ce52de5` (behind 0, no conflicts). No WF-A source is touched here.
Protected paths `financial_engine/`, `finco_core/`, `domain/`: **unchanged** (empty diff against main). No release flag, pin map, golden or CI workflow is changed.
F3 multi-Senior activation is **enabled** in this release (`multisenior_config.ACTIVATION_ENABLED = True`); Junior, F4/P2, Revenue V3, M6 and M7 stay release-closed and are untouched.

## 1. Source inventory and ownership (one coordinator this pass)

| Area | Files |
|---|---|
| Revenue / PPA | `revenue_contracts.html`, `model_revenue_contract_editor.js`, `model_revenue_contract_editor.css`, `_build_revenue_contract_editor` (read-only operating window, boundaries, PPA term) |
| Shared date control | `_date_duration.html`, `date_duration.js` |
| Construction timing | `sheet_project_setup.html`, `construction_timing.js`, `grid_csrf_token` in `_base_sheet_ctx`, toolbar OOB in `_render_htmx_sheet` |
| Flowbite layer | `tools/ui/*` (build), `static/css/flowbite_finco.min.css`, `static/vendor/flowbite.min.js`, `fx_ui.js`, `THIRD_PARTY_NOTICES.md` |
| Navigation | `workspace_destinations.py` (labels, new `financing` area; tab and area ids otherwise unchanged) |
| Run History | `sheet_run_history.html`, `run_history_detail.html`, `run_history_compare.html`, `run_compare_expanded.html`, `model_v2_run_history.css` |
| Financing / Investors | `_financing_multisenior.html`, `_investor_f4.html` (wording, controls, badges) |
| Strip / progress | `inputs_grid_v1.css` (strip never re-wraps), `workbook_v2.css` (scoped busy label) |
| Not touched | Trust sheet, Diagnostics wording, methodology registry, export, persistence repositories |

## 2. Delivered

### Workstream B - PPA and revenue
- **Guided Add a PPA** (Fixed / Indexed / Scheduled): generated IDs, derived dates, contract reference required from the user (never invented), existing Save path (owner, CSRF, composite CAS, scenario scope), Run stays separate. Old toolbar relabelled "Other contract types" inside a Flowbite accordion (open by default).
- **Section 3.1 atomic Add**: every check (dates, boundaries, operating periods, price, allocation, reference) runs before the contract book is touched; a rejected Add leaves it unchanged (`test_a_rejected_scheduled_add_leaves_the_contract_book_untouched`).
- **Section 3.2 completeness against the operating axis**: a Scheduled contract is an incomplete draft (Save disabled) when a required period is missing, a date repeats, a date is outside the contract or not an operating period, or a price is negative/invalid; removed points are never re-inferred; points are date-ordered when a date is committed. Backend validation remains authoritative.
- **Allocation feedback**: "Contracted production up to X%, residual Merchant takes the remainder / unallocated up to Y%"; contracted shares above 100% in any segment block Save. Unsaved contract edits block a scenario change or a Run instead of being lost.
- **Scenario restoration**: Base and Alternative contract books are independent (`test_base_and_alternative_scenario_contracts_are_restored_independently`).

### Addendum D - Start + Duration -> End
- One shared control (`date_duration.js`), used for PPA and construction.
- **Calendar convention** (identical to the model, dateutil `relativedelta`, verified against Python for every documented case): N calendar months are added; when the target month is shorter the day is clamped to its last day (31 Jan + 1 month = 28/29 Feb). A year is 12 calendar months, never 365 days; a month is never 30 days. Duration must resolve to a whole positive number of months (zero, negative, fractional-month, comma and text are refused).
- **PPA**: start + duration -> read-only end; "Specify end date manually" unlocks it, keeps the calculated date as the first value, preserves it while other fields change, shows the implied duration when exact; "Use calculated end date" returns to automatic mode. Dates must be **operating-period boundaries** (the canonical Revenue V2 rule: start and end in the set of operating period starts and ends); otherwise Add is blocked with the nearest boundary offered as a button the user must press. Nothing is snapped silently.
- **Construction** (finance authority finding): the workbook inputs are `cod_date` and `construction_months`; construction start is **derived** (COD minus months, month-end clamped) and the engine requires start + months = COD exactly (`PERIOD_AXIS_COD_MISMATCH` otherwise). The control therefore shows the derived start, computes COD from start + duration, saves both fields atomically through `/workbook/grid/save`, refuses combinations the engine could not reproduce (month-end) and a manual end that is not a whole number of months. No second timeline authority is created. Existing PPAs are never rewritten when timing changes.
- **Pre-existing finance risk (reported, not changed)**: `build ... _subtract_months` followed by the engine's `relativedelta` addition is not a round trip for some month-end CODs (for example COD 31 Mar with 1 month); the control blocks those, the field editors do not.
- A construction configuration that moves COD to 2031-01-01 (12 months from 2030-01-01) made the engine fail closed at Run ("integrity checks stopped this run"); this is a model refusal for that input set, not a UI defect, and the journeys use a configuration that runs.

### Workstream C - Debt, Equity, Run History
- **Debt**: proposal vs active is explicit: SAVED PROPOSAL carries a "Not active in Run" badge and the note that saved terms do not affect the model until activated; an inactive proposal leaves the Run results identical (KPI comparison); with activation ticked the status is ACTIVE and the Run contains both facility schedules.
- **Investors**: ownership vs funding wording; ownership 60/40 with paid-in 70/30 saves, reloads and Runs; changing ownership alone leaves project returns, revenue, CAPEX and debt KPIs identical; ownership summing to 90% is refused with a visible message and nothing is saved; unreconciled paid-in capital never commits a Run.
- **Run History (UX-024)**: the "Back to Run History" control was dead (its target `#v2-sheet-run-history` no longer existed after the swap) - fixed; long identity values wrap instead of widening the document (found at 1366 px); tables scroll in a keyboard-reachable region; the list now shows STALE after a Save.

### Workstream A - presentation
- Navigation hierarchy: Inputs, Financing, Results, Scenarios, Analysis, Model Checks, Trust.
- **Flowbite layer** (section 4), light/dark, toasts for Save/Run.
- **Scroll review (section 7)**: see section 6.

## 3. Test evidence (real Chromium, real CSP, no bypass)
Run on this branch (local, `FINCO_TEST_CHROMIUM_PATH` set, Python 3.12):

| Group | Result |
|---|---|
| Affected non-browser suites (92 files + RC-UX unit suites, 2839 tests) | **2831 passed, 4 skipped, 4 failed**; the 4 failures are environmental in this sandbox: 3 in `test_ci_acceptance.py` (`No module named 'yaml'`) and `test_ui_protocol_shell.py::test_api_b04_placeholders_not_links` (no Chromium path set for that group) - not code failures, they must be green in CI |
| Existing browser suites (consolidation, hybrid grid, capital stack, investor F4, Goal Seek, cost grid editing, cost batch save; 117 tests) | 109 passed, 8 failed at first run. Triage: 4x capital-stack and 1x cost-grid failures were stale test expectations (the unsupported list is now a Flowbite accordion, not `<summary>`; plain arrows no longer change numbers since PR #286 - that test also fails on `main`); updated accordingly. Re-verification of the remaining 3 (consolidation legacy-links, investor wind, cost-grid ten-edit) was still running when this PR was opened - see the PR comment/body for the final count |
| Phase 2 browser suites (PPA 32, construction timing 16, Flowbite 11, Run History 2, scoped progress 2, debt/equity journeys 6; 69 tests) | 67 passed; 1 failed (Run History: an error toast from a mis-detected Run result covered the Detail button) -> toast result detection now reads the committed state and error toasts auto-dismiss; re-run pending |

Real-CSP guarantee: none of the Phase 2 suites uses `bypass_csp`; they fail on any `EvalError`, console error or page error (favicon excluded, as in the consolidation suite).
Flowbite acceptance (`test_rcux2_flowbite_ui_browser.py`, 11 cases, last full run 11/11): assets self-hosted and no third-party host; computed styles prove the Flowbite classes apply (8 px radius, 1 px border, shadow, light and dark palettes); accordion toggles once after repeated HTMX settles; accessible dismissible toast; loading toast then result toast on Run; no document overflow at 390 px dark on Overview, Revenue, Debt, Investor and Run History.

## 4. Flowbite adoption - what is Flowbite and what is not
| Component | Source | Reason |
|---|---|---|
| Form controls (PPA, construction timing, investor inputs), buttons, badges, KPI cards, alert-style state strip, table styling in Run History | Flowbite 2.5.2 markup/utilities, built once with Tailwind 3.4.17 (`tools/ui`), scoped under `.fx-ui`, preflight off | Meaningful modernisation without touching the existing numerical tables; scoping prevents global restyling |
| Accordion (advanced contract tools, Financing "Not available in this release") | Flowbite JS (`data-accordion`) | Initialised once per element id; re-initialised after every HTMX settle; proven not to double-toggle |
| Toast / loading toast (Save, Run) | Flowbite toast markup + Dismiss, wrapper in `fx_ui.js` | Events already emitted by the Save/Run flows; text only; fixed region placed inside the `.fx-ui` scope |
| Navigation (hybrid nav), tabs, Inputs grid, cost grids, financial tables | Existing FINCO components | Roving-tabindex ARIA tablist with deep links, keyboard editing and numeric density are pinned by mandatory tests; Flowbite Tabs would duplicate state |
| Datepicker, tooltips, charts, datatables | Not adopted | Native date inputs work under the CSP; no benefit |
No CDN, no `unsafe-eval`, no change to the CSP. The Flowbite plugin forms/tooltips base styles are disabled so no existing control is restyled.

## 5. Performance (local Chromium, not staging)
Local Chromium, 1440x900 light, first load of each sheet. Before = `main`, after = this branch (Flowbite layer included). Server render time dominates; no calculation time is affected.

| Sheet | First response ms (main / branch) | Load event ms (main / branch) | Subresource KB (main / branch) | Document overflow (main / branch) |
|---|---|---|---|---|
| Overview | 1876 / 838 | 3045 / 3176 | 540 / 725 | no / no |
| Revenue | 2171 / 1883 | 2921 / 2851 | 2 / 2 | no / no |
| Debt | 2064 / 1602 | 3199 / 2350 | 2 / 2 | no / no |
| Investor | 1966 / 1991 | 3150 / 3144 | 2 / 2 | no / no |
| Run History | 1837 / 2034 | 2843 / 2860 | 2 / 2 | **yes / no** |

Static cost of the Flowbite layer: `flowbite.min.js` 135.8 KB (29.6 KB gzip), `flowbite_finco.min.css` 19.5 KB (3.0 KB gzip), plus `fx_ui.js`, `date_duration.js`, `construction_timing.js` (about 14 KB). Differences in first-response time are within the run-to-run noise of one local measurement per cell and are not claimed as improvements. This is not staging and not a statement about calculation speed.
Screenshots (5 screens x 4 viewports, before and after) were captured locally under `artifacts/rcux2-screens/` (git-ignored) and shared in the session.

## 6. Scroll assertion review (`test_four_consecutive_edits_save_atomically_with_stable_focus_and_scroll`)
- Reproduced: on `main` the Save leaves `scrollY` 120 -> 120, document height 3400 -> 3400, cell top unchanged. On this branch before the fixes: `scrollY` 120 -> 95, document height 3424 -> 3556, cell top +0.6.
- Two real regressions were behind it (not scroll anchoring alone): (1) the new toast region was unscoped and sat in the page flow (+132 px after Save); (2) the persistent strip re-wrapped to a second line when the "N unsaved edits" chip appeared (+24.4 px in `#v2-hybrid-bar`, measured clean vs staged: main 0, branch +24.4), caused by the extra navigation group.
- Fixed: toast region moved inside the scope element; the strip stays on one line on desktop (identity text ellipsizes), the unsaved chip keeps its space.
- After the fixes: clean vs staged heights are identical to main (0 delta), and Save moves neither `scrollY` nor the cell. The **original absolute `scrollY` assertion is restored** (the earlier relaxation is reverted); a stronger check that the edited cell stays within 2 px is added. No timeout or unrelated assertion was weakened.
- Immediate vs staged cost-edit modes: covered by the existing `test_cost_grid_editing_browser_v1.py` and `test_cost_batch_save_browser_v1.py`, run in the regression below.

## 7. Governed wording - proposal only (needs explicit owner approval; nothing below is changed)
| Existing wording | Proposed wording | UI location | Financial / governance impact | Approval |
|---|---|---|---|---|
| Trust (area label and tab) | Model Audit | Hybrid nav, tab bar | Presentation only; deep link `#trust` and tab id `tab-trust` unchanged | Owner (Trust wording is governed) |
| Model Trust Pack | Model audit evidence | `sheet_trust.html` title | None; pins in Trust governance tests need exact-content successor | Owner + governance successor |
| Model Diagnostics | Model Checks | `sheet_diagnostics.html` h1, nav item, Overview link | None; RC-3 exact-content pins | Owner + governance successor |
| QM-xxx check IDs in row subtitles | Move to the details expander, keep the meaningful title | Diagnostics heatmap/list | None | Owner |
| "Canonical Senior terminal ..." and similar | "Senior debt ..." | `sheet_outputs.html`, `_financing_trace.html` | None | Owner (some strings pinned) |
| Reference regression / synthetic evidence copy | "Reference check (example data)" in the technical details only | `_trust_validation_body.html` | Must keep "not independently verified" meaning | Owner |

## 8. UX finding matrix (original descriptions from the audit)
Status vocabulary: FIXED, PARTIAL, UNRESOLVED, AUTHORITY BLOCKED, NOT REPRODUCIBLE. Totals: AUTHORITY BLOCKED 3, FIXED 17, NOT REPRODUCIBLE 1, PARTIAL 9, UNRESOLVED 1. PARTIAL means at least one relevant sub-finding is not verified.

| ID | Sev | Original finding | Status | Evidence / limitation |
|---|---|---|---|---|
| UX-001 | P0 | Trust sheet / strip name an older Run than the toolbar after a new Run | FIXED | PR #286 `test_ux_a_result_coherence.py` |
| UX-002 | P1 | Persistent strip keeps the previous Run time/scenario | FIXED | PR #286 `ResultStatus`; Run History now also follows a Save (`test_history_identities_and_states_are_truthful...`) |
| UX-003 | P1 | OPEX Y1 total shows a stale `display_value` | FIXED | PR #286 `test_ux_c_strict_numbers.py` (static contract) |
| UX-004 | P1 | Goal Seek result lost to the lazy-panel GET race | FIXED | `test_ux_a_goal_seek_race_browser.py` (real CSP) |
| UX-005 | P1 | OPEX sticky columns leave an uncovered band | FIXED | PR #286 CSS variable; static test, no pixel measurement |
| UX-006 | P2 | Engineering copy in primary screens (50 audit entries) | PARTIAL | About 20 entries rewritten in ordinary screens (Model Checks, empty states, revenue/returns/financing/investor wording, reason sentences, Run History evidence, stale-save). The remaining entries are mostly in Trust/Diagnostics (governed, report section 7) or were not reached |
| UX-007 | P2 | Revenue header disagrees on a vertical | NOT REPRODUCIBLE | The audit itself could not reproduce it after reload |
| UX-008 | P2 | Trust 18-19k px tall on 390 px | AUTHORITY BLOCKED | Trust content and structure are governed (exact-content pins); a contained-scroll or disclosure change needs the owner's approval and a governance successor |
| UX-009 | P2 | Mixed dark/light treatment, no theme control | PARTIAL | Theme control (Auto / Light / Dark on the existing `data-theme`) and a dark palette for the new components are tested; legacy screens were not all re-themed and no contrast measurement was run |
| UX-010 | P2 | Three project/Run-state zones repeat; Run Model twice | PARTIAL | The CURRENT banner and the overview CURRENT strip are no longer shown and the strip keeps state only (identity stays for assistive technology) - `test_a_current_state_is_presented_once...`; STALE/NOT RUN/errors stay visible. Two Run Model buttons remain because many mandatory tests drive both |
| UX-011 | P2 | All assumptions / Project & Technical / Technical assumptions overlap | PARTIAL | Labels are now Assumptions grid / Project setup / Inputs summary and the area hierarchy is Inputs > Financing > Results > Scenarios > Analysis > Model Checks (`test_the_inputs_navigation_labels_no_longer_overlap`); deep pages on the legacy shell were not migrated |
| UX-012 | P2 | 'Running…' shown on commands whose own request is not active | FIXED | `test_rcux2_progress_scope_browser.py` |
| UX-013 | P2 | Raw LLCR/DSRA reason codes | PARTIAL | Ordinary screens (Overview integrity, Insight reasons) show a plain sentence with the typed code beside it (`test_rcux2_display_labels.py`); the raw codes in Diagnostics are governed: AUTHORITY BLOCKED |
| UX-014 | P2 | Two rows labelled model period 4 | FIXED | The periods are distinct (construction vs operations share the index at the boundary); only the label changed to `3 · construction` / `3 · operations` (`test_a_model_period_index_shared...`); no index, date or amount changed |
| UX-015 | P2 | Goal Seek 43-62 s with text-only progress | FIXED | Real states only (request sent, finished, failed) for Goal Seek, apply, sensitivity and matrix (`test_goal_seek_progress_reports_only_real_states`); no percentage, solver untouched |
| UX-016 | P3 | Crowded OPEX heading/subtitle, stretched badge | FIXED | Compact headings and constrained badge; duplicate projection title removed (`test_opex_headings_are_compact...`) |
| UX-017 | P1 | Cost cells normalise `410 420 430` to 410420430 | FIXED | PR #286 `test_ux_c_strict_numbers.py` |
| UX-018 | P2 | Arrows change the number in cost cells | FIXED | PR #286; the stale cost-grid test now asserts Alt-nudge (it also failed on main before) |
| UX-019 | P2 | Add/Duplicate drops other staged edits | FIXED | PR #286 guard for failed unsaved rows; static contract |
| UX-020 | P2 | Rename of the active scenario not shown | FIXED | PR #286 `test_a_renamed_active_scenario_label...` |
| UX-021 | P3 | Rejected stale-tab save: message x3, rejected value implied | FIXED | `test_a_stale_tab_save_is_rejected_once_clearly_without_overwriting_newer_data` (two real views: one inline message, truthful wording, Reload action, server CAS untouched) |
| UX-022 | P2 | 'End date (exclusive)' vs boundary-only dates; bare JSON error | FIXED | Guided Add a PPA states the rule, blocks with an actionable message and offers the nearest boundary (`test_a_duration_ending_off_the_period_boundary...`); the legacy table editor still relies on the server message |
| UX-023 | P2 | Scenario tariff override with explicit contracts makes the scenario unrunnable | AUTHORITY BLOCKED | `scenario_revenue_authority.py` is financial-authority adjacent |
| UX-024 | P2 | Run History detail: unbounded width, Python reprs, dead Back | FIXED | `test_rcux2_run_history_browser.py` (width, Back at 1440/1366/390 light+dark) and structured evidence as a summary with the exact stored value in a contained block (`test_rcux2_display_labels.py`) |
| UX-025 | P2 | Export identity (template id as project id, unknown build fields) | AUTHORITY BLOCKED | Protected export contract |
| UX-026 | P3 | AI Import counters contradict the confirmation page | PARTIAL | One definition of Exact mappings (field id or exact registry label) from the import transaction's proposals (`test_rcux2_import_counters.py`); the header row still counts as a detected row (import-authority change, not made) |
| UX-027 | P3 | Back leaves the workbook; unknown project redirects silently | FIXED | Unknown and foreign projects get one identical, non-revealing library notice (`test_rcux2_navigation_safety.py`); hash navigation already created history entries (`test_legacy_links_context_navigation_history_and_keyboard`) |
| UX-028 | P2 | 4.76 MB document, 23k DOM nodes, multi-second first response | UNRESOLVED | Re-measured under comparable conditions (3 loads each, local): main 4613 KB / 22,715 nodes (21,505 hidden), branch 4632 KB / 22,807 nodes; first response 680-990 ms on both. The weight is the post-Run state (a fresh project is 774 KB); no safe reduction was made. No improvement claimed |
| UX-029 | P2 | No main/h1/skip link, contrast, table captions | PARTIAL | Landmarks and skip link (PR #286); every table now has an accessible name and every header a scope, one level-1 heading (`test_every_table_has_an_accessible_name...`); contrast was not measured |
| UX-030 | P3 | Mobile 390: Save bar, tap targets, font, Trust height | PARTIAL | Primary controls >= 44 px, 16 px field text, grid Save bar pinned at the bottom (`test_phone_controls_meet_the_44px_target...`); not every control and not Trust height |
| UX-031 | P2 | Three error styles on Run/Save failures | PARTIAL | PR #286: refusal sentences lead, codes trail; the stale-save refusal now follows it; not every error source was converted |

## 9. Financial and governance approvals still required
- Optional or draft-persisted `source_ref` for Working PPA contracts (schema/validation change) - not done, not needed for this UX.
- Capability gaps (price base year, partial indexation share, market-linked pricing, contracted volume limits, P50/P90 lender pricing): REQUIRES FINANCIAL AUTHORIZATION (see the capability matrix in the previous revision of this document; unchanged).
- Construction: a month-end COD round trip (`_subtract_months` vs `relativedelta`) is a pre-existing finance-adjacent edge case that needs an owner decision (adapter or engine side); the UI blocks it.
- Trust / Diagnostics wording (section 7).
- UX-025 export identity (protected export contract), UX-023 tariff override while explicit contracts exist (`scenario_revenue_authority.py`), UX-008 Trust mobile structure and the raw reason codes inside Diagnostics (UX-013): governed content.

## 10. Revenue capability matrix (no engine change proposed here)
| Capability | Status |
|---|---|
| Fixed price, indexed price, scheduled price points | SUPPORTED DIRECTLY (contract editor, guided Add a PPA) |
| Residual Merchant / contracted share | SUPPORTED DIRECTLY (explicit Merchant price entered by the user) |
| Indexation basis | SUPPORTED WITH CONFIGURATION (operating-year basis only) |
| Term relative to COD | SUPPORTED WITH CONFIGURATION (start + duration are converted to boundary dates; the contract schema has no "years from COD" field) |
| Step pricing | SUPPORTED WITH CONFIGURATION (scheduled price points) |
| Price base year, partial indexation share | MISSING / REQUIRES FINANCIAL AUTHORIZATION |
| Market-linked pricing, contracted volume limits | REQUIRES FINANCIAL AUTHORIZATION |
| P50/P90 lender pricing | REQUIRES FINANCIAL AUTHORIZATION (the Commercial / Bank-case comparison is read-only) |
| Optional or draft-persisted `source_ref` | REQUIRES FINANCIAL AUTHORIZATION |
