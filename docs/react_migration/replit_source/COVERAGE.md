# FINCO Design coverage — Iteration 15

## Scope and status definitions

This inventory describes the isolated React/TypeScript design sandbox, not FINCO production. The canonical module families below were supplied in the task; this iteration did not inspect GitHub or independently verify release status. “Interactive demo” means local visual interaction with synthetic values, never a live model.

- **Interactive Demo** — local controls/navigation/editing exercised in this prototype.
- **Visual Only** — rendered sample content without a meaningful state-changing behavior.
- **Gated / Unavailable** — explicitly shown as preview-only, unavailable, or not activated.
- **Missing / Unverified** — no working design surface was confirmed.

## Module matrix

| FINCO concept | Design destination | Sandbox status and limits |
| --- | --- | --- |
| Project Library | `ProjectLibrary.tsx`, `_shared/demoWorkingCopies.ts` | **Interactive Demo.** Search/filter, open five fictional reference samples read-only, create a unique session-only Working Copy with parent attribution, reopen after in-tab navigation/reload, create a local demo project, and reset the session registry. No server clone, durable save, auth, or canonical reference permissions. |
| Workbook shell, navigation, working context | `ModelWorkspace.tsx`, `_shared/FincoShell.tsx`, `_workbook/WorkbookNavigation.tsx` | **Interactive Demo.** Seven main sections, workbook catalog, project/mode/parent identity, local status, Save/Run separation and trust boundary. Reference mode disables editable form controls and Save/Run in the client; no server permission boundary or durable save. |
| Hybrid Input Grid | `_workbook/InputGrid.tsx`, `_workbook/gridPaste.ts` | **Interactive Demo.** Scalar cells, validation, staged edit, undo, keyboard movement and bounded TSV validation. Scalar draft is isolated by demo project ID in browser session. No financial formula engine. |
| Project setup, timeline, tax | `_workbook/TimelineTaxWorkspace.tsx` | **Interactive Demo / Visual Only.** Input-style controls and validation are illustrative. Tax, depreciation, timing effects, and financial roll-through are not calculated. |
| Revenue and multi-PPA | `_workbook/RevenueWorkspace.tsx` | **Interactive Demo.** PPA-A/B/C records and Fixed/Indexed/Scheduled editor modes have local demo drafts. Browser edited/re-opened each contract draft and checked mode controls; records do not calculate revenue or statements. Merchant residual, P50/P90, allocation and availability are disclosures or placeholders, not active model behavior. |
| CAPEX cost lines / construction period planner | `_workbook/CostLinePlanner.tsx`, `_workbook/period-grid.css` | **Interactive Demo.** 18-month construction example, editable cells, local Save, profile choices and validated rectangular demo paste. Fixed summaries are not recalculated; no backend row-level CAS save. Browser and unit checked. Demo rectangle paste must not be mapped to production bulk line persistence. |
| OPEX categories / operating period planner | `_workbook/CostLinePlanner.tsx`, `_workbook/period-grid.css` | **Interactive Demo / layout stress fixture.** 12-quarter editable display; 6-half-year is a fixed reference, not an aggregation. 60Q/30H is a fixed example; 80Q/40H and 120Q/60H are layout stress only, with post-60Q cells locked/unavailable. No escalation, step-up, forecast or financial roll-through. Browser and unit checked. |
| Senior A/B, Junior, SHL, Equity | `_workbook/FinanceWorkspace.tsx` | **Interactive Demo.** Five selectors and separate local record drafts; modified records were individually acknowledged with local Save and verified after switching. No debt sizing, sculpting or calculations. |
| Sources & Uses, reserves, debt schedule | `_workbook/FinanceWorkspace.tsx`, `_workbook/CreditDecisionWorkspace.tsx` | **Visual Only / Interactive Demo navigation.** Fixed synthetic snapshot and entry points. Browser checked S&U/DSRA/DSRF disclosures, credit context selectors and Senior↔Mezzanine statement schedule navigation. No balancing, reserve sizing, construction draw/IDC math or facility schedule reconciliation. |
| Credit / lender review | `_workbook/CreditDecisionWorkspace.tsx` | **Interactive Demo / Visual Only.** Institutional layout with explicit unassessed states. No covenant math, actual bankability decision, or green lender pass. |
| P&L, Balance Sheet, Cash Flow, CFADS, Debt, Sponsor Returns | `_workbook/StatementWorkbook.tsx`, `_workbook/statements.css` | **Interactive Demo navigation; fixed synthetic rows.** Six sheets, annual/model period and Senior/Mezzanine facility display controls, row groups, scroll, source-section trace and context return. Browser checked all six sheets, both period views and the Senior→Mezzanine→Senior trace/scroll restoration path. Values do not reconcile or recalculate; trace is navigation, not calculation lineage. |
| Results, KPI, charts, Run History, scenario comparison | `ResultsAnalysis.tsx` | **Interactive Demo / Visual Only.** Fixed synthetic IRR/NPV/DSCR and statements; panels and selections are illustrative. No real Run record, persisted provenance, or changed output on input edit. |
| Scenario management and multi-Run compare | `_workbook/ScenarioGovernanceWorkspace.tsx`, `ResultsAnalysis.tsx` | **Interactive Demo / Visual Only.** Base/Downside/Upside local drafts, project-scoped demo state, history selection and 2→3 fixed-run selection were browser exercised. These are authored references, not executed runs; outputs do not change and no computed differences exist. |
| Sensitivity and Goal Seek | `_workbook/DecisionAnalysisWorkspace.tsx` | **Visual Only / Unavailable.** Reachable design surfaces; no sensitivity engine, solver, or numeric recalculation. |
| Diagnostics, Trust Pack, run provenance | `_workbook/ModelDeliveryWorkspace.tsx` | **Visual Only / Unavailable.** Status and trust presentation only. Integrity is not evaluated; engine/version identity is unknown/not connected; history is synthetic. |
| Excel migration / import / export | `_workbook/ModelDeliveryWorkspace.tsx` | **Gated / Unavailable.** Design entry point only; no workbook parser, file import/export, or generated production workbook. |
| Developer, acquisition, BESS, data-center, EV, other technology modules | `_workbook/ModuleSurface.tsx` | **Gated / Unavailable.** Preview/capability-gated design surfaces only. No vertical financial model behavior was verified. |
| Mock typed transport adapter | `_shared/demoAdapter.ts` and `scripts/demoAdapter.test.mjs` | **Isolated test-only demo spike.** Fake-transport tests; not wired to any API and not evidence of production contracts. |

## Iteration 12-C evidence

- Browser smoke: 13/13 cases passed using `scripts/finco-browser-smoke.mjs`, including real Chromium clicks/keyboard and 1440/900/390 layout checks; exact steps and limits are in `BROWSER_ACCEPTANCE.md`.
- Unit tests: 8 period-grid tests and 6 isolated fake-adapter tests passed.
- Typecheck and Vite production build passed with the sandbox’s required `PORT=5000 BASE_PATH=/` build environment.
- Selected contrast samples for period-grid save state, column header and metric label measured at 6.34:1, 7.71:1 and 6.77:1 after a targeted status-color correction. This is not a full accessibility audit.
- Long-horizon DOM-change-to-two-animation-frame, wheel and keyboard-focus observations are stored in `test-evidence/iteration-12c-browser-results.json`; they include CDP/test harness overhead and are not a performance benchmark.
- Screenshots: `test-evidence/i12c-library-1440.png`, `i12c-workspace-900.png`, `i12c-results-390.png`, `i12c-opex-120q-390.png`.

## Highest-priority design/integration gaps

1. No canonical server validation, persisted working copy, CAS/409 UI, or true Last Run freshness.
2. No financial engine, formula evaluation, cross-statement reconciliation, or calculation lineage.
3. Sources & Uses, reserves, debt schedules/sculpting, P50/P90 sizing and lender/covenant review are non-computational examples.
4. Scenario, Multi-Run Compare, Sensitivity and Goal Seek lack real independent run data and calculation behavior.
5. No actual workbook import/export, mapping, validation report, or migration workflow.
6. No real auth, permissions, read-only reference enforcement at a server boundary, or production feature-gate contract.
7. Cost-line grid save/paste semantics are local demo semantics only; production persistence policy must be verified against canonical code.
8. Technology-gated BESS/data-center/EV/developer/acquisition surfaces are placeholders.
9. Accessibility checks are targeted only: no axe, screen reader, cross-browser or full WCAG audit; sampled contrast and reduced-motion behavior are not comprehensive.
10. The UI is not connected to any verified production API; all field IDs, response envelopes, endpoint paths, and permission contracts remain unverified.

## Production release status

No production FINCO release status is asserted here. Any architecture facts provided in the assignment are recorded as owner-supplied context in `INTEGRATION_READINESS.md` and require independent GitHub/source verification before integration.

## Iteration 13 closure evidence

- `I13-A` in `scripts/finco-browser-smoke.mjs` passed in real Chromium: Reference edit/Save/Run blocked; a Working Copy received a unique ID and parent reference, accepted a local edit and Save, remained separate from the Reference and a second copy (121 vs 123), survived same-tab navigation/reload, and was removed by session reset.
- Latest browser suite: **14/14 cases passed**. The suite includes the three original preview routes at 1440/900/390, prior keyboard/grid/debt/trace/scenario/gate cases, and the new reference-copy journey. Exact steps and constraints are in `BROWSER_ACCEPTANCE.md`.
- New deterministic registry tests: **3/3 passed**. Existing synthetic period-grid tests: **8/8 passed**. Fake adapter tests: **7/7 passed**. Fresh sandbox TypeScript typecheck and Vite build passed.
- New screenshots and machine-readable browser results: `test-evidence/i13-library-1440.png`, `i13-workspace-900.png`, `i13-results-390.png`, `i13-opex-120q-390.png`, and `iteration-13-browser-results.json`.
- The Reference/Working Copy workflow is still only a sessionStorage design demo. It does not prove production copy semantics, authorization, persistence, or independent engine outputs. Reference and Working Copy share synthetic fixtures and fixed results.
- Advanced Revenue, Developer, Acquisition, BESS/Storage, Data Center and EV destinations were clicked and confirmed `UNAVAILABLE / GATED`; Excel migration/import/export and Goal Seek remain disabled. This verifies truthful UI gating, not release status in FINCO.

## Iteration 14 closure evidence

- **Browser:** `pnpm test:browser` completed **17/17 PASS** in Chromium/CDP. New evidence covers two session-only Working Copies with separate scalar, PPA-A, Senior A, scenario, CAPEX and OPEX drafts; same-tab reload; 390px Reference→copy→sheet→trace journey; visible-control/named-navigation scan; and F2/Esc focus restoration. Existing within-project browser coverage switches PPA-A/B/C and Senior A/B/Junior/SHL/Equity. Cross-copy PPA-B/C and all-facility isolation, new-tab session behavior, OS clipboard and full WCAG remain unverified.
- **Unit tests:** `test:working-copies` **3/3**, `test:demo-adapter` **11/11** (test-only fake transport), and `test:period-grid` **9/9**. Period-grid tests include blank/oversized rectangles, atomic rejection, dates, zero, locked rows, and the 60Q edit boundary.
- **Responsive:** real browser checks cover all three existing routes at 1440/900/390 (9 combinations, no document-level horizontal overflow), plus a detailed mobile Reference→Working Copy→CFADS trace/return journey. Sticky period header/metric and internal scroll were exercised. 320px and cross-browser behavior were not tested.
- **Accessibility:** bounded DOM checks found one main landmark per route and computed names for the visible controls; F2→Esc focus return passed. A manual checklist exists at `ACCESSIBILITY_MANUAL_CHECKLIST.md`; no axe, screen-reader, full WCAG or independent contrast audit was run in this iteration.
- **Grid keyboard:** browser checked CAPEX Ctrl+Z against the edited row/cell (Enter advances selection), and prior scalar-grid keyboard/undo behavior remains covered. TSV browser events are synthetic; the OS clipboard path is not tested.
- **Component handoff:** `InputGridProps` and `CostLinePlannerProps` are exported presentation boundaries. Fixture/session/URL state remains coupled in parts of the app, notably `StatementWorkbook`; no production adapter or endpoints were introduced. See `UI_COMPONENT_HANDOFF.md`.
- **Performance:** 60/80/120Q timings are small headless Chromium/CDP smoke samples with harness overhead, not user-facing benchmarks. Current samples and caveats are in `BROWSER_ACCEPTANCE.md` and `test-evidence/iteration-14-browser-results.json`.
- **Canvas:** the three original frames remain the intended design surfaces: `finco-library`, `finco-workspace`, and `finco-results`. No new FINCO frame was added.

The application remains a design-only synthetic demo: Working Copies and saves are session-local; fixed statements/KPIs do not recalculate. Production field IDs, permissions, canonical persistence/CAS, calculation/run provenance and release gates remain `NEEDS_GITHUB_VERIFICATION`.

## Iteration 15 full-React harvest evidence

- **Cross-copy coverage expanded:** the I15 browser suite tested a Reference plus two session-only Working Copies across scalar Input Grid, PPA-A/B/C, Senior A/B, Junior, SHL, Equity, Base scenario, CAPEX and OPEX; Save and same-tab reload were checked. These are browser-tab-local drafts, not server-persisted copies. Fixed KPI/statements remain shared synthetic references.
- **Single-root composition:** an internal composition proof imports the same three existing FINCO pages and changes their view under one React root. It is not a new Canvas screen or a production route/API shell.
- **Statement presentation boundary:** `StatementWorkbook` accepts typed `StatementWorkbookSnapshot`/`StatementRunStatus` props via `_workbook/statementContract.ts`; the existing synthetic fixture remains the default and has not been fully extracted from the component.
- **Accessibility correction and smoke:** the Project Library breadcrumb is now a named navigation landmark. Chromium checked named navigation/control labels across all three pages and F2→Esc focus restoration. Full axe, screen-reader, WCAG, cross-browser and OS clipboard review remain untested.
- **Browser suite:** `test:browser` passed **18/18** after Iteration 15 code changes. It covered all three routes at 1440/900/390, two-copy record isolation, mobile Reference→Working Copy→trace, grids, statements, scenario/history, gating and console errors. Details and exact limits are in `BROWSER_ACCEPTANCE.md`; durable artifacts are `test-evidence/iteration-15-browser-results.json` and `test-evidence/i15-*.png`.
- **Typed presentation contract:** `test:statement-contract` has **2/2** checks for display-only zero/unavailable and freshness/integrity/engine-status labels. This is not a real adapter or persisted Run.
- **Full React target:** `INTEGRATION_READINESS.md` and `DESIGN_HARVEST_MANIFEST.md` now reflect the selected React+TypeScript+Vite frontend with legacy Jinja2/HTMX retained as reference. The selected architecture is a design decision, not evidence of backend/API compatibility.
- All outputs remain fixed **SYNTHETIC DEMO DATA**. No financial calculations, persistence, auth, production integration, GitHub changes, publishing or deployment were introduced.

## Iteration 16 full-React transfer evidence

- **Standalone app assembly:** `src/finco-transfer/main.tsx`, `App.tsx`, `routes.ts` and `context.tsx` provide a separate React-owned entry and typed route/context boundary. It lazily imports the existing `ProjectLibrary`, `ModelWorkspace` and `ResultsAnalysis` exports. The existing Canvas entries remain unchanged.
- **Typed fixture/presentation seams:** `demoProjectFixtures.ts` now owns the Library reference fixture; `ProjectLibraryProps.sampleProjects` accepts an external typed list. `ResultsAnalysisProps` accepts a statement snapshot and run-status input, and the transfer route supplies the fixed synthetic fixture in `src/finco-transfer/fixtures.ts`. `InputGridProps` and `CostLinePlannerProps` remain controlled component boundaries; their parent still owns demo/session state. `PpaDraftViewModel` and `FacilityDraftViewModel` are interface contracts, not production DTOs or connected providers.
- **Source classification:** direct reuse in the transfer entry: the three existing page components and their workbook child components. With adapter: URL navigation, project identity, and external statement snapshot/status. Refactor before production reuse: page-level sessionStorage/URL state and component-owned fixtures, especially `ModelWorkspace` and statement presentation state. Rebuild: production auth, API/data provider, canonical Save/CAS, real Run/Last Run projection and server permissions.
- **W1/W3:** existing component composition and a separately buildable transfer entry passed fresh typecheck and both Vite builds. `build:transfer` outputs a standalone `dist-transfer/index.html`; no new artifact or Canvas frame was created.
- **W2/W4:** typed route/view models and a fixed synthetic statement provider are in place. Unit route/provider checks passed 5/5; the existing fake adapter passed 12/12. The fake adapter remains isolated test code, and not every typed view-model is wired to the visible components.
- **W5/W7:** real Chromium/CDP browser suite passed 19/19, including Library→Reference→Working Copy→Save→Results, Back/Forward, explicit unavailable route, 1440/900/390 transfer-route document-width checks, existing grid and workbook interactions, and no uncaught browser errors. Full WCAG/axe, screen-reader and OS clipboard remain untested.
- Current source/test evidence is in `BROWSER_ACCEPTANCE.md`; reusable source inventory is in `DESIGN_HARVEST_MANIFEST.md` and `UI_COMPONENT_HANDOFF.md`.
- All outputs remain fixed **SYNTHETIC DEMO DATA**. No production endpoint, auth, backend, engine, DB, live financial math, GitHub change, deploy or publish was performed.
