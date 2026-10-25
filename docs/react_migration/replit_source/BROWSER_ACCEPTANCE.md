# FINCO Design — browser acceptance record

## Scope and method

This records tests of the isolated Replit Design mockup only. It is not production-model, financial, persistence, authentication, or API acceptance. All figures are fixed synthetic examples.

- Browser: local Chromium controlled through the dependency-free CDP smoke script `scripts/finco-browser-smoke.mjs`.
- Repeat: `pnpm --filter @workspace/mockup-sandbox run test:browser`.
- Historical Iteration 12-C baseline: **13/13**; Iteration 13: **14/14**. Latest Iteration 14 run: **17/17 cases passed** in fresh Chromium/CDP interaction.
- Build: fresh `pnpm --filter @workspace/mockup-sandbox run typecheck` and `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build` passed.
- Screenshots captured from actual preview routes:
  - Current Iteration 14: `test-evidence/i14-library-1440.png`, `i14-workspace-900.png`, `i14-results-390.png`, `i14-opex-120q-390.png`, `i14-reference-copy-390.png`, `i14-mobile-statement-390.png`
  - Historical Iteration 13: `test-evidence/i13-library-1440.png`, `i13-workspace-900.png`, `i13-results-390.png`, `i13-opex-120q-390.png`
- Latest machine-readable run record: `test-evidence/iteration-14-browser-results.json`. Prior Iteration 12-C and 13 evidence remains preserved below.

The smoke script dispatches real browser mouse/keyboard input. Clipboard cases dispatch a `ClipboardEvent` with explicit test text; the operating system clipboard was not used. This is a repeatable browser smoke suite, not a CI suite or a complete accessibility audit.

## Acceptance cases

| ID | Result | Evidence |
| --- | --- | --- |
| I12-01 Preview routes and responsive widths | **PASS** | Chromium loaded the three existing Project Library, Model Workspace, and Results & Analysis preview routes. All three routes were checked at 1440, 900, and 390 px (9 route/width combinations); no document-level horizontal overflow was detected. The 390 px Results screenshot shows the compact mobile navigation and KPI layout. |
| I12-02 Library and project identity | **PASS** | Actual search/filter narrowed the project list, opened a Wind sample, and added a local demo row. The selected project name and technology appeared in the workspace. |
| I12-03 Workbook keyboard, validation, paste, Save/Run, context | **PASS** | Browser exercised F2, Enter, Shift+Enter, Esc, arrows, Tab/Shift+Tab, Ctrl/Cmd+Z, validation recovery, valid and invalid scalar TSV, dirty Run blocking, local Save separate from fixed demo Run, and project switching. The Solar draft remained `121` while the separately scoped Wind draft changed to `86`; switching back restored each value. Fixed results remained illustrative and unchanged. |
| I12-04 CAPEX/OPEX period grids | **PASS** | Edited period cells; CAPEX valid rectangle TSV staged and invalid negative rectangle was rejected without changing the staged cells; recovered and saved locally with `NOT RUN`. Checked CAPEX 18 months; OPEX 12Q/6H, 60Q/30H and 80/120Q layout-stress views. At 120Q the post-60Q tail is locked/unavailable, not a forecast. Horizontal scroll kept the metric label anchored; real vertical scroll kept the period header at the scroller top. |
| I12-05 PPA and facility selection | **PASS** | Browser edited and re-opened separate PPA-A/B/C drafts, switched Fixed/Indexed/Scheduled mode, and edited/re-opened separate Senior A/B, Junior, SHL and Equity drafts. The Sources & Uses destination was reached; its numbers remain a fixed snapshot. |
| I12-06 Statements and source navigation | **PASS** | Opened all six statement sheets, switched Annual/Model periods, horizontally navigated, opened a statement-to-input trace and returned with an actual pointer click. The trace row no longer sits under the sticky metric header. This verifies navigation only, not numerical lineage. |
| I12-07 Analysis, history, diagnostics, trust | **PASS for exercised demo scope** | Scenario and history, 2-to-3 fixed-run selection, credit context selectors, Sources & Uses, Sensitivity, unavailable Goal Seek, Diagnostics, Trust, and gated import/export were clicked and checked for distinct destinations and honest status. No engine behavior is implemented. |
| I12-08 Browser errors | **PASS** | No uncaught runtime exception or `console.error` was captured. Preview HMR/WebSocket Back-Forward Cache notices, when emitted by Chromium navigation, are recorded separately and token-redacted. |
| I12-09 Debt statement facility selector | **PASS** | Actual keyboard round-trip Senior → Mezzanine → Senior verified distinct schedule rows, period basis, row-group expand/collapse, trace navigation and return restoration of facility, row, period and horizontal scroll. |

## Iteration 12-C targeted acceptance

| ID | Result | Evidence |
| --- | --- | --- |
| I12C-01 Debt facility and trace regression | **PASS** | Real browser selector changes Senior → Mezzanine → Senior; verified facility-specific row content, Annual/Model-period switch, group visibility and `aria-expanded`, period 3 trace context, and restoration of facility, expanded row, selected cell and scroll position. This is display/navigation only, not debt lineage. |
| I12C-02 Project/scenario/history isolation | **PASS for tested local demo paths** | Base/Downside/Upside values were edited and saved independently; Solar and Wind Base assumptions (4 and 6) remained project-scoped. Multi-Run selection changed from 2 to 3 fixed sample records. After saving changed PPA/facility/scenario drafts, the actual demo Run opened the same fixed KPIs and history remained three authored rows. Library has no Reference-copy workflow; it remains missing. |
| I12C-03 Credit, Sources & Uses, gated delivery and analysis | **PASS for navigation/state truth** | Changed P90/Senior B/model-period selectors; checked `NOT ASSESSED`, absence of a passing covenant cell, unreconciled S&U/DSRA/DSRF disclosures, disabled import/export, sensitivity selection, disabled Goal Seek solver, Diagnostics and Trust unavailable states. |
| I12C-04 Long periods, responsive/sticky behavior and accessibility sample | **PASS for tested display behaviors; PARTIAL accessibility audit** | 60/80/120Q fixtures rendered repeatedly in headless Chromium; 120Q grid retained internal horizontal scroll and no document overflow at 1440/900/390. At 390, vertical scrolling kept the header anchored; keyboard focus/ArrowRight moved between cells; period 61 was locked. Reduced-motion setting used `scroll-behavior:auto`. Computed contrast samples were 6.34:1 for save status, 7.71:1 for header, 6.77:1 for metric label after the targeted color correction. No axe or screen-reader audit. |

### Timing samples (headless Chromium/CDP)

Three repeated horizon changes were measured at 1440px by dispatching the UI select change and timing through two animation frames. At 390px, three horizontal wheel and keyboard-focus events were measured through the browser harness. These include browser scheduling and harness waits; they are not real-user latency benchmarks.

| Check | Samples (ms) | Median / range |
| --- | --- | --- |
| 60-quarter render | 303.5, 256.8, 260.7 | 260.7 / 256.8–303.5 |
| 80-quarter render | 317.2, 305.6, 312.4 | 312.4 / 305.6–317.2 |
| 120-quarter render | 602.3, 612.3, 596.7 | 602.3 / 596.7–612.3 |
| Horizontal wheel at 390px | 183, 188, 184 | 184 / 183–188 |
| Keyboard focus at 390px | 456.7, 445.4, 453.7 | 453.7 / 445.4–456.7 |

## Targeted correction made

Earlier in Iteration 12, `src/components/mockups/finco-model/_workbook/StatementWorkbook.tsx` and `statements.css` were corrected so the source-trace row uses one non-sticky spanning header cell; Chromium confirmed the click opens the intended workspace section and returns to the statement.

In Iteration 12-C, the computed contrast check found the period-grid save-state label below 4.5:1 because a shared card-title span rule overrode its local text color. `src/components/mockups/finco-model/_workbook/period-grid.css` now uses a more specific selector and darker navy-gray. The three sampled labels measured 6.34:1, 7.71:1 and 6.77:1. This is a targeted sample, not a full WCAG audit.

Long-horizon timing samples and their measurement limitations are preserved in `test-evidence/iteration-12c-browser-results.json`. They include CDP/browser scheduling and test-harness overhead; wheel timing includes the harness settling wait, so none should be read as user-perceived latency or a general performance benchmark.

## Limits and outstanding verification

- Clipboard tests dispatch a browser `ClipboardEvent` with fixture text; OS clipboard integration is not tested. Cost-grid paste is local demo staging, not production multi-row persistence; canonical cost-line saves are per-row serial CAS.
- The 80/120-quarter layouts are stress-only synthetic display fixtures. Only the first 60 quarters are editable; no escalation, aggregation or forecast is generated.
- Timing samples are small headless Chromium/CDP observations, not controlled benchmarks.
- No axe, screen-reader, cross-browser or full-page WCAG audit was run. Contrast measurement covered three selected labels only.
- Reference-vs-Working-Copy creation, true independent persisted projects/scenarios, production Save/CAS, Run, financial calculations, formulas, reconciliation and numerical lineage are not implemented.
- Some catalog destinations are visual or explicitly gated. Navigation reachability does not mean an engine feature exists.
- This preview has no financial engine, live formulas, backend, durable persistence, real Run provenance, authentication, or production integration.

## Iteration 13 acceptance — latest run

| ID | Result | Actual browser evidence |
| --- | --- | --- |
| I13-01 Reference → Working Copy | **PASS** | Chromium opened Adriatic Solar I as a Reference; verified Reference banner and disabled Save/Run, attempted F2 and confirmed no editor. The Library also discloses that portfolio totals/charts are fixed reference snapshots. Created a local Working Copy with distinct ID and parent attribution, edited capacity 120→121, used local scalar Save, and verified the visible acknowledgement says no backend write/Run. |
| I13-02 Copy isolation, duplicate identity, reload and reset | **PASS** | Returned to Library, opened Reference and confirmed it remained 120; created a second copy with a unique ID and `(2)` label, changed/Saved it as 123, then reopened the first copy at 121; same-tab reload/navigation preserved the first copy. Reset cleared the session-only copy registry. This is browser-session behavior, not persistence. |
| I13-03 Capability gates | **PASS for tested UI truth** | Clicked advanced Revenue, Developer Economics/Decision, Acquisition, BESS/Storage, Data Center and EV destinations and asserted distinct page content plus `UNAVAILABLE / GATED`. Existing checks also exercised disabled Goal Seek and Excel import/export, NOT ASSESSED credit, unreconciled Sources & Uses/reserves, Diagnostics and Trust. |
| I13-04 Existing workbook regression suite | **PASS** | The same run passed the prior scalar grid keyboard/paste/Save-vs-Run, CAPEX/OPEX, PPA/facility, six statements, scenario/history/compare, debt statement trace-return, and 60/80/120-period responsive/sticky checks. No financial outputs changed. |
| I13-05 Responsive previews and browser console | **PASS for tested paths** | All three original preview routes loaded at 1440/900/390 (nine route-width checks); no document-level horizontal overflow. The 390px Results screenshot was captured. No uncaught runtime exception or `console.error`; transient Vite HMR/Back-Forward Cache notices were separately classified. |

The final recorded run is **14/14 browser cases, 0 failed**. During test development, one run exposed an incorrect test locator for the correctly disabled Reference Save control, and another run had one transient timeout in the existing debt trace-return test; the locator was corrected and the complete suite then passed. A subsequent complete rerun also passed 14/14. No reproducible application defect was confirmed from those intermediate runs.

Iteration 13 additions:

- `pnpm --filter @workspace/mockup-sandbox run test:working-copies` — 3/3 passed (registry IDs, independent draft scope/clean save baseline, duplicate names and local-project attribution).
- `pnpm --filter @workspace/mockup-sandbox run test:demo-adapter` — 7/7 passed, including preservation of an unavailable fixed statement and `STALE` after a demo Save.
- `pnpm --filter @workspace/mockup-sandbox run test:period-grid` — 8/8 passed.
- Fresh `typecheck` and `PORT=5000 BASE_PATH=/ ... run build` passed after the source changes.
- The test harness writes Iteration 13 screenshots/results to new `i13-*` and `iteration-13-*` filenames to avoid replacing the prior baseline on subsequent runs.

Reference locking is client-side visual/demo behavior only. The workflow does not establish server authorization, canonical project cloning, durable storage, independent financial model state, or project-specific result calculations. A full screen-reader/axe/WCAG review remains untested.

## Iteration 14 acceptance

| ID | Result | Actual evidence and limits |
| --- | --- | --- |
| I14-W1 Cross-copy state isolation | **PASS for exercised same-tab demo paths** | Chromium created two session-only Working Copies from a read-only Reference. Copy A/B separately staged and locally saved scalar input, PPA-A, Senior A, Base scenario, CAPEX and OPEX values; switching/reopening kept those values distinct from each other and the Reference. Same-tab reload restored A. Existing tests separately switch PPA-A/B/C and Senior A/B/Junior/SHL/Equity within one project. Fixed KPI/statements and authored history remained unchanged. New-tab behavior and cross-copy PPA-B/C plus every facility are not claimed tested; all real persistence remains absent. |
| I14-W2 Responsive working-copy journey | **PASS at 390px for this path** | Real Chromium clicks: Library → Reference → Create Working Copy → mobile sheet picker → PPA-B → CAPEX inner scroll/sticky metric/Save → CFADS → trace and return. Document width stayed within 390px. The route/width sweep also loaded all three frames at 1440/900/390 (9 combinations) with no document-level horizontal overflow. |
| I14-W3 Accessible names and focus recovery | **PASS for bounded DOM/keyboard smoke; full audit UNTESTED** | Scanned visible controls and named navigation on ProjectLibrary (17 controls), ModelWorkspace (99), and ResultsAnalysis (153), with one main landmark per route. Real F2→Esc returned focus to the selected period-grid cell. Axe, screen-reader, full WCAG 2.2 AA and cross-browser testing were not run. See `ACCESSIBILITY_MANUAL_CHECKLIST.md`. |
| I14-W4 Presentation boundaries | **PARTIAL** | Exported `InputGridProps` and `CostLinePlannerProps` provide typed view boundaries. Fixture/session/URL ownership is not fully separated; `StatementWorkbook` remains coupled to its fixed synthetic fixture. No behavior or production API was added. |
| I14-W5 Mock adapter | **PASS for the isolated fake contract only** | `test:demo-adapter` passed 11/11: save, validation, 409 without retry, simulated 401/403, Reference rejection, stale response, scenario mismatch, missing Run, freshness/integrity separation, zero/unavailable, and Save without Run. It is not wired to the app or a real endpoint. |
| I14-W6 Period-grid edge checks | **PASS for bounded local demo behavior** | `test:period-grid` passed 9/9, including blank/oversized TSV atomic rejection, invalid dates, zero, locked rows, and the 60Q editable limit for 80/120Q stress fixtures. Browser confirmed CAPEX staged-cell Ctrl+Z, valid and rejected paste, Save≠Run, frozen metric/header and internal horizontal/vertical scrolling. Clipboard was synthetic `ClipboardEvent`; OS clipboard remains untested. |
| I14-W7 QA and evidence | **PASS for recorded sandbox checks** | Latest browser suite 17/17; test command checks three preview routes, 1440/900/390, copy isolation, mobile flow, grids, workbook navigation and browser errors. Fresh typecheck/build results are recorded in `INTEGRATION_PREP_PROGRESS.md` after the final source edits. |

### Iteration 14 performance samples

Headless Chromium/CDP, three horizon-change samples each, 1440px: 60Q **297.7, 313.5, 259.3 ms**; 80Q **324.6, 307.2, 308.2 ms**; 120Q **600.0, 586.6, 628.6 ms**. At 390px, horizontal wheel samples were **183, 182, 183 ms** and focus samples **452.6, 449.7, 449.7 ms**. The smoke harness measures DOM/UI action plus scheduling and wait overhead; these are not controlled or user-perceived performance benchmarks.

The final smoke run observed no uncaught runtime exceptions, `console.error`, or browser-log errors. Two transient Vite HMR/WebSocket Back-Forward Cache notices were separately recorded with preview tokens redacted. Screenshots and structured results are under `test-evidence/i14-*.png` and `test-evidence/iteration-14-browser-results.json`.

## Iteration 15 acceptance

### Fresh browser run

`pnpm --filter @workspace/mockup-sandbox run test:browser` completed **18/18 PASS, 0 FAIL** in Chromium/CDP after the Iteration 15 changes. This is a UI/demo test, not financial-model validation.

| ID | Result | Actual browser evidence and limits |
| --- | --- | --- |
| I15-01 Full React route composition | **PASS** | One React root loaded the existing Project Library, Model Workspace and Results & Analysis components in turn using in-page route selection. No fourth Canvas frame was created. |
| I15-02 Preview routes and responsive widths | **PASS for tested layouts** | All three preview routes at 1440/900/390 (9 combinations); no document-level horizontal overflow. Test saved I15 screenshots. This is not cross-browser or full WCAG coverage. |
| I15-03 Two-copy PPA/facility isolation | **PASS for same-tab demo state** | Reference baseline plus two session-only Working Copies. The test read/changed/locally saved PPA-A/B/C and Senior A/B, Junior, SHL and Equity values, then switched contexts and verified no cross-copy bleed; scalar, Base scenario, CAPEX/OPEX and same-tab reload were also checked. Fixed financial outputs remain shared synthetic references. New-tab and durable/server persistence are not claimed. |
| I15-04 Mobile Reference-to-copy workflow | **PASS at 390px** | Real browser journey: Library → protected Reference → create session-only copy → mobile workbook picker → PPA-B → CAPEX internal scroll/sticky metric/Save → CFADS → source trace → return. No document overflow. |
| I15-05 Accessibility smoke | **PASS for bounded checks; full audit UNTESTED** | Visible-control accessible-name and named-navigation scan on all three pages; actual F2→Esc focus restoration passed. Axe, screen reader, full WCAG and OS clipboard were not tested. |
| I15-06 Existing grid, statements, context and gates | **PASS** | The same run exercised scalar edit/undo/atomic TSV/Save≠Run, CAPEX/OPEX, PPA and financing controls, all six statement sheets/period switch/trace return, scenarios/history/compare, credit/Sources & Uses, gated migration/vertical modules, 60/80/120Q stress and Back/Forward. |
| I15-07 Console | **PASS for captured journey** | No uncaught runtime exception, `console.error`, or browser-log error. Two transient Vite HMR/WebSocket Back-Forward Cache notices were recorded separately with preview tokens redacted. |

Machine-readable evidence and screenshots are `test-evidence/iteration-15-browser-results.json` and `test-evidence/i15-*.png`. Period-grid stress timings include harness overhead and are not user-facing performance benchmarks. The browser test’s synthetic clipboard paste event does not prove OS clipboard integration.

### Source/build-only evidence and limits

- `test:statement-contract` has 2 unit checks for zero vs unavailable display and run-status labels. It does not prove a server-backed Last Run projection.
- `StatementWorkbook` now accepts typed optional `snapshot` and `status` props, but its default fixture remains inside the component; a clean fixture/provider extraction is not complete.
- The hidden composition proof exercises existing components under one React-owned root, but does not create a production Vite app, API adapter, real route/auth system, or backend integration.
- Browser flows do not establish production persistence, permissions, financial correctness, calculations, formula lineage, lender decisions, or output reconciliation. These remain explicitly out of scope.

## Iteration 16 — Full React transfer RC1

### Fresh build and browser acceptance

The final Iteration 16 Chromium/CDP run completed **19/19 PASS, 0 FAIL** with `pnpm --filter @workspace/mockup-sandbox run test:browser`. The run exercised the existing preview routes and a separate in-app transfer route that reuses the same three TSX screens. It did not add a Canvas frame.

| ID | Result | Actual browser evidence and limits |
| --- | --- | --- |
| I16-01 Single-root and standalone React routes | **PASS** | Existing pages were composed under one root, then exercised through the separate `/__mockup/finco-transfer/` entry. Routing stayed in-page for Library → Reference → Working Copy → Save → Results, and displayed a statement supplied by the typed transfer fixture. |
| I16-02 Reference/copy and Save boundary | **PASS for session-only demo** | Opened a read-only reference, verified its Save control was disabled, created a session-only working copy, edited/saved a scalar, and confirmed the workspace showed the local demo-save state. This is not a server-side clone or persistence. |
| I16-03 Responsive transfer routes | **PASS for tested widths** | Library, Workspace and Results were measured at 1440/900/390px. No document-level horizontal overflow was observed. Representative transfer screenshots are under `test-evidence/i16-transfer-*.png`; existing preview route screenshots are `test-evidence/i16-*.png`. |
| I16-04 Browser history and unavailable route | **PASS** | Back/Forward restored the transfer Workspace/Results route; an unknown route showed the explicit unavailable page. The render-error boundary is implemented but an induced component exception was not tested. |
| I16-05 Existing FINCO flows | **PASS** | Same run covered keyboard grid editing/undo/atomic paste, CAPEX/OPEX, PPA-A/B/C, facility drafts, six statement sheets, period/facility switching, trace-return, scenarios/history/compare, diagnostics/trust, credit and gated surfaces. |
| I16-06 Browser console | **PASS for exercised flows** | No uncaught runtime exception, `console.error`, or browser-log error. Two transient Vite HMR/WebSocket Back-Forward Cache notices were separately recorded with preview tokens redacted. |

Final structured evidence: `test-evidence/iteration-16-browser-results.json` (19/19); screenshots: `test-evidence/i16-*.png`.

During authoring, early smoke attempts exposed test-harness issues (regex syntax, text/selector assumptions, route-transition timing and session cleanup); these were corrected and the final full run passed. This is not a claim that the financial model was validated.

**Historical evidence caveat:** an early I16 smoke attempt used the former I15 output names before the script was corrected. It changed `test-evidence/i15-library-1440.png`, `test-evidence/i15-reference-copy-390.png`, and `test-evidence/iteration-15-browser-results.json`. Do not treat those three paths as pristine I15 evidence; use the I16 result and `i16-*.png` files for current evidence. No source files or Canvas registrations were removed.

### Fresh build and unit checks

- `pnpm --filter @workspace/mockup-sandbox run typecheck` — PASS.
- `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build` — PASS.
- `BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build:transfer` — PASS; emitted a standalone `dist-transfer/index.html`.
- `test:demo-adapter` **12/12**, `test:working-copies` **3/3**, `test:period-grid` **9/9**, `test:statement-contract` **2/2**, `test:transfer-routes` **5/5** — PASS (31 unit checks total).

The Canvas inspection still reports the three intended FINCO iframes `finco-library`, `finco-workspace`, and `finco-results` as live. A separate generic Artifact iframe is not a FINCO page.

### Limits

The transfer entry is an isolated, buildable UI assembly only. It has no production API, auth, canonical DTOs, persistence, calculation engine, formulas, financial reconciliation, immutable Run record, or lender/integrity assessment. Axe, screen-reader, full WCAG and OS clipboard behavior remain untested. The fake adapter is test-only and is not wired into the visible transfer app.
