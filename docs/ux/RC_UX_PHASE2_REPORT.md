# RC-UX Phase 2 - final report (branch `feat/model-rcux2-institutional-workspace`)

Base: `origin/main` `03e2b9638e9324bb18ea8420ce8f9823f4f0a676` (PR #286 merged). PR #287 (WF-A numerical and credit validation) was **open** at the last check and is not merged; no WF-A source is touched here.
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
REG_PLACEHOLDER

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
PERF_PLACEHOLDER

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
| ID | Sev | Original finding | Status | Evidence / limitation |
|---|---|---|---|---|
| UX-001 | P0 | Trust sheet / strip name an older Run than the toolbar after a new Run | FIXED — VERIFIED | PR #286: `test_ux_a_result_coherence.py`; PR #286 browser CI |
| UX-002 | P1 | Persistent strip keeps the previous Run time/scenario after a Run | FIXED — VERIFIED | PR #286 `ResultStatus`; this branch: Run History also follows Save (`test_history_identities_and_states...`) |
| UX-003 | P1 | OPEX Y1 total shows a stale `display_value` | FIXED — VERIFIED | PR #286 `test_ux_c_strict_numbers.py` (static contract) |
| UX-004 | P1 | Goal Seek result lost to the lazy-panel GET race | FIXED — VERIFIED | `test_ux_a_goal_seek_race_browser.py` (6 cases, real CSP) incl. the CSP-safe lifecycle |
| UX-005 | P1 | OPEX sticky columns leave an uncovered band | FIXED — VERIFIED | PR #286 CSS variable; static test only, no pixel measurement |
| UX-006 | P2 | Engineering copy in primary screens (50 audit entries) | UNRESOLVED — NOT ACCEPTED | About 15 entries rewritten (Model Checks, empty messages, revenue/returns/financing/investor wording); the remaining entries sit mostly in Trust/Diagnostics (governed, section 7) or were not reached |
| UX-007 | P2 | Revenue header disagrees on vertical | NOT REPRODUCIBLE — EVIDENCE ATTACHED | Audit itself: not reproduced after reload (`POST_RC3_MODEL_STAGING_ACCEPTANCE.md`) |
| UX-008 | P2 | Trust 18-19k px tall on 390 px | UNRESOLVED — NOT ACCEPTED | Trust is governed; not changed |
| UX-009 | P2 | Mixed dark/light treatment, low link contrast, no theme toggle | UNRESOLVED — NOT ACCEPTED | Dark palette applied to the new Flowbite components and tokens (`test_dark_mode_uses_the_dark_flowbite_palette`); the legacy screens and the toggle are not done |
| UX-010 | P2 | Three project/Run-state zones repeat; Run Model twice | UNRESOLVED — NOT ACCEPTED | Header duplication remains (visible in the screenshots) |
| UX-011 | P2 | All assumptions / Project & Technical / Technical assumptions overlap | UNRESOLVED — NOT ACCEPTED | Area hierarchy Inputs > Financing > Results > Scenarios > Analysis > Model Checks done and tested; the three overlapping Inputs labels are unchanged |
| UX-012 | P2 | 'Running…' shown on commands whose own request is not active | FIXED — VERIFIED | `test_rcux2_progress_scope_browser.py` (2 cases) |
| UX-013 | P2 | Raw LLCR/DSRA reason codes | UNRESOLVED — NOT ACCEPTED | Not reached |
| UX-014 | P2 | Two rows labelled model period 4 | UNRESOLVED — NOT ACCEPTED | Not re-tested in the audit; not reached |
| UX-015 | P2 | Goal Seek 43-62 s with text-only progress | UNRESOLVED — NOT ACCEPTED | Run now has a loading toast; Goal Seek/Sensitivity progress not changed |
| UX-016 | P3 | Crowded OPEX heading/subtitle | UNRESOLVED — NOT ACCEPTED | Not reached |
| UX-017 | P1 | Cost cells normalise `410 420 430` to 410420430 and persist it | FIXED — VERIFIED | PR #286: `test_ux_c_strict_numbers.py` (browser module + writer boundary) |
| UX-018 | P2 | Arrows change the number in cost cells | FIXED — VERIFIED | PR #286 static contract (Alt needed to nudge) |
| UX-019 | P2 | Add/Duplicate drops other staged edits | FIXED — VERIFIED | PR #286 guard for failed unsaved rows; static contract |
| UX-020 | P2 | Rename of the active scenario not shown | FIXED — VERIFIED | PR #286 `test_a_renamed_active_scenario_label...` |
| UX-021 | P3 | Rejected stale-tab save: message x3 and the rejected value stays | UNRESOLVED — NOT ACCEPTED | Not reached |
| UX-022 | P2 | 'End date (exclusive)' but only period-end boundaries are accepted; server returns bare JSON | FIXED — VERIFIED | Guided Add a PPA states the boundary rule, blocks with an actionable message and offers the nearest boundary (`test_a_duration_ending_off_the_period_boundary...`); the legacy table editor still relies on the server message |
| UX-023 | P2 | Scenario tariff override while explicit contracts exist makes the scenario unrunnable | BLOCKED — AUTHORITY REQUIRED | `scenario_revenue_authority.py` is financial-authority adjacent |
| UX-024 | P2 | Run History detail: unbounded width, Python reprs, dead Back | FIXED — VERIFIED (width, Back) | `test_rcux2_run_history_browser.py` (list/detail/compare/expanded at 1440, 1366, 390 light + 390 dark; Back works; no document overflow). Python-repr evidence rendering: UNRESOLVED |
| UX-025 | P2 | Export identity (template id as project id, unknown build fields) | BLOCKED — AUTHORITY REQUIRED | Protected export contract |
| UX-026 | P3 | AI Import counters contradict the confirmation page | UNRESOLVED — NOT ACCEPTED | Not reached |
| UX-027 | P3 | Back leaves the workbook; unknown project redirects silently | UNRESOLVED — NOT ACCEPTED | Not reached |
| UX-028 | P2 | 4.76 MB document, 23k DOM nodes, multi-second first response | UNRESOLVED — NOT ACCEPTED | Measured before/after (section 5); no regression, no improvement claimed |
| UX-029 | P2 | No main/h1/skip link, contrast, table captions | UNRESOLVED — NOT ACCEPTED | PR #286 added main, h1 and skip link; contrast and captions not done |
| UX-030 | P3 | Mobile 390: Save bar, tap targets, Trust height | UNRESOLVED — NOT ACCEPTED | 390 px no-overflow tests for the new forms, history and Flowbite screens only |
| UX-031 | P2 | Three error styles on Run/Save failures | FIXED — VERIFIED | PR #286 (`test_ux_b_error_copy.py`): refusal sentences lead, code trails; not every error source converted |

## 9. Financial and governance approvals still required
- Optional or draft-persisted `source_ref` for Working PPA contracts (schema/validation change) - not done, not needed for this UX.
- Capability gaps (price base year, partial indexation share, market-linked pricing, contracted volume limits, P50/P90 lender pricing): REQUIRES FINANCIAL AUTHORIZATION (see the capability matrix in the previous revision of this document; unchanged).
- Construction: a month-end COD round trip (`_subtract_months` vs `relativedelta`) is a pre-existing finance-adjacent edge case that needs an owner decision (adapter or engine side); the UI blocks it.
- Trust / Diagnostics wording (section 7).
- UX-025 export identity (protected export contract) and UX-023 tariff override while explicit contracts exist (`scenario_revenue_authority.py`, financial-authority adjacent).

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
