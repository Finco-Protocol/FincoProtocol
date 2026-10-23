# FINCO Design coverage — Iteration 15

## Iteration 20 statement-provider addendum

`_workbook/StatementWorkbook.tsx` is now a typed presentation consumer of an explicit `StatementWorkbookSnapshot | null` and `StatementRunStatus`; it contains no statement row/period fixtures and imports no synthetic provider. `ResultsAnalysisView.tsx` receives caller-owned snapshot/status props. The existing Canvas route keeps `ResultsAnalysis.tsx` as its demo-only wrapper, which injects `syntheticStatementProvider.ts`; the standalone transfer route imports the view directly and injects its independent `src/finco-transfer/fixtures.ts` snapshot. An explicit `null` renders an unavailable state with no fixture substitution. All financial values remain fixed synthetic examples; no calculations or numerical lineage were added.

Fresh evidence: statement/provider contract tests **7/7**, full unit tests **39/39**, Chromium browser **22/24 PASS, 0 FAIL, 2 UNTESTED** (axe and Firefox/WebKit), and fresh typecheck plus Design/transfer builds passed. The built transfer assets were checked to confirm the Canvas-only statement fixture is absent. See `BROWSER_ACCEPTANCE.md` and `FINCO_STATEMENT_PROVIDER_I20_REPORT.md`.

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

## Iteration 17 — RC2 source/build and browser evidence

- **Interactive demo — PASS:** two independently keyed, session-only Working Copies plus read-only Reference were browser-checked across scalar inputs, PPA-A/B/C, all five demo financing records, Base/Downside/Upside, CAPEX/OPEX and navigation. Copy-specific drafts are local session data; the fixed financial statements/KPIs remain shared synthetic reference output.
- **Transfer build — PASS:** an exact-version standalone manifest, independent TypeScript config and pnpm lockfile were added. A clean extracted package installed, typechecked, and built; the served transfer build passed direct-route/reload and asset MIME checks.
- **Browser regression — PASS:** Chromium suite 19/19; no uncaught browser errors in the final run. 1440/900/390 document overflow checks, 60/80/120-period stress, grid scroll/focus, statement trace and existing workbook flows were exercised. Performance observations and screenshot paths are recorded in `BROWSER_ACCEPTANCE.md`.
- **Mock provider tests — PASS:** 15/15 test-only cases, including project/scenario drift, concurrent edit during save, 401/403/422, stale CAS without retry, missing/zero values, status separation and unchanged fixed output.
- **Other unit tests — PASS:** working copies 3/3, period-grid 9/9, statement contract 2/2, transfer routes 5/5 (34 total across the five suites).
- **Accessibility — PARTIAL:** named landmarks and selected keyboard/focus behaviors were checked; axe, full screen-reader/WCAG and OS clipboard are not verified.
- **Unavailable / integration pending:** no API, auth, persistence, real Run, engine, formulas, financial reconciliation, lender result, production DTOs or GitHub integration. All canonical production mappings remain subject to independent GitHub verification.
- Current evidence: `BROWSER_ACCEPTANCE.md`, `TRANSFER_RC2_PROGRESS.md`, and `FINCO_REACT_TRANSFER_RC2_REPORT.md`.
- **Iteration 18 addendum (initial run):** skip-link and explicit keyboard activation support were added to existing FINCO navigation/trace controls. That snapshot showed 20/24 PASS, 2 FAIL and 2 UNTESTED.
- **Iteration 19 Correction A:** both reproduced browser failures were resolved: copy isolation now starts from a committed origin in the harness, and the statement table uses a roving keyboard tab stop with focus restoration. Full suite is now **22 PASS, 0 FAIL, 2 UNTESTED** (axe and Firefox/WebKit unavailable). Unit suites are **35/35 PASS**; typecheck and both builds PASS. Details and limitations are in the latest `BROWSER_ACCEPTANCE.md` section and `FINCO_REACT_I18_CORRECTION_A_I19_REPORT.md`.

## Iteration 21 — Results presentation boundary

| Area | Current Design state | Evidence / boundary |
| --- | --- | --- |
| Results / Analysis presentation | **Interactive demo view with typed caller-owned props** | `ResultsAnalysisView` renders supplied KPIs, periods, summary rows, chart geometry, credit observations, capital structure, scenarios, and history. It contains no embedded FINCO synthetic values or fixture import. |
| Canvas Results demo | **Synthetic-only composition** | `ResultsAnalysis.tsx` supplies `_results/syntheticResultsProvider.ts` only when props are omitted. Explicit `null` stays unavailable; it never falls back to the fixed sample. |
| Standalone transfer Results | **Separate synthetic fixture provider** | `src/finco-transfer/resultsFixtures.ts` is independent from the Canvas provider and supports demo, partial, caller-provided stale, and empty/not-run display states. |
| Financial math/provenance | **Unavailable / not implemented** | The contract includes no formula evaluator, reconciliation, calculation lineage, or persistence. Supplied chart coordinates and display strings are not derived from workbook data. |
| Results accessibility | **PARTIAL** | Enter/Space trace activation is browser-tested. Axe 4.14.0 found one serious-impact scroll-region rule on `#fm-wb-grid-scroll` despite keyboard focus evidence; Firefox/WebKit, screen reader and full WCAG remain untested. |

I21 browser acceptance is **22 PASS / 1 PARTIAL / 0 FAIL / 1 UNTESTED** across 24 cases; fresh unit suites are 45/45. See `BROWSER_ACCEPTANCE.md` and `FINCO_RESULTS_PROVIDER_I21_REPORT.md`. This change does not alter production availability claims or the selected full React + TypeScript + Vite target.

## Iteration 22 addendum — latest tested UI status

| Area | Current Design state | Evidence / boundary |
| --- | --- | --- |
| Input Grid read-only Reference keyboard access | **Interactive, browser-tested in scanned state** | Reference mode leaves the grid scroll region keyboard-accessible while existing cell/editor guards prevent edits and Save/Run. Axe 4.14.0 final scan had no violations on the three tested views; incomplete checks remain. |
| Credit observation / debt statement trace | **Interactive synthetic demo** | Facility/period selection, evidence context and navigational statement link work; Back restores selected context. Fixed Run ID only; no lender decision, covenant status or calculation lineage. |
| Scenario and fixed-Run comparison | **Interactive synthetic demo** | Scenario and up-to-three fixed Run references have distinct selections and browser history restoration. Results stay fixed while Working Copy assumptions change. No Run execution or recalculation. |
| Source authority drawer | **Interactive synthetic disclosure** | Supports selected PPA, CAPEX/OPEX line-period and financing facility examples. Source/workbook relation is conceptual navigation, not verified data lineage. |
| Accessibility finding | **PASS for the scanned axe states; broader audit UNTESTED** | I21 serious scroll-region and row-number contrast findings addressed; I22 axe scan reported zero violations. Screen reader, full WCAG, Firefox and WebKit remain untested. |
| Full React production integration | **NOT IMPLEMENTED** | Demo-only view models and fixtures are not production DTOs; server authority, auth/CSRF, CAS, persisted Run, permissions and feature gates still require independent FINCO verification. |

Latest full Chromium run: **27/28 PASS, 0 FAIL, 1 UNTESTED** (Firefox/WebKit unavailable). Fresh unit suites total **45/45**; typecheck and Design/transfer builds PASS. See `BROWSER_ACCEPTANCE.md` and `FINCO_RESULTS_WORKBOOK_I22_REPORT.md`.

## Iteration 23 — product-state and period-compare coverage

| Area | Design state | Evidence / limitation |
| --- | --- | --- |
| Working Copy / Last Run state matrix | **Interactive transfer-harness demo** | Selector previews NOT RUN, fixed illustrative CURRENT, edited STALE, failed-attempt-with-prior-Last-Run, unavailable, and protected Reference. Status metadata is UI-only; a “failed attempt” is not a real Run. |
| Current vs stale result context | **Interactive, browser-tested** | Working Copy scenario ID/state and prior Last Run scenario/timestamp are separate; engine currency UNKNOWN and integrity NOT EVALUATED remain separate. Static values are unchanged between states. |
| Scenario comparison period basis | **Explicit unavailable disclosure** | Scenario snapshots do not provide period frequency/date coverage; UI states that no periods are aligned or inferred. It does not silently compare rows. |
| Multi-Run comparison periods | **Interactive synthetic fixture** | Three fixed Run references display separate annual/quarterly/semiannual calendars and exact period labels. Missing metrics remain unavailable; per-period schedules are not aligned across runs. |
| PPA/CAPEX/OPEX/Financing provenance | **Interactive synthetic disclosure** | PPA-B, CAPEX, OPEX and Junior/Mezzanine source-authority panels were clicked in Chromium. Link to workbook sections is conceptual navigation only, not verified lineage. |
| Accessibility | **PASS for selected axe/keyboard states; PARTIAL overall** | axe-core 4.14.0 reported 0 violations on three Canvas states, with incomplete checks remaining. Keyboard-only existing flows and internal table scroll passed. No full WCAG, screen-reader, Firefox/WebKit or physical-device Safari claim. |
| Browser/viewport acceptance | **PASS for exercised Chromium** | Latest full suite 29/30 PASS, 0 FAIL, 1 UNTESTED (Firefox/WebKit). Three frames plus local transfer build checked at 1440/900/390/320; the new Run Compare view checked at 390. No document-level overflow observed. |
| Test and build status | **PASS** | Unit suites 47/47; TypeScript typecheck, Design build, transfer build, and scoped `git diff --check` passed. See `BROWSER_ACCEPTANCE.md` for exact evidence. |

New I23 state and run-period fixtures are not production data contracts. Existing Canvas financial screens and all outputs remain synthetic. The final I23 diff contains no generated preview registry change; the three existing Canvas frames were retained.
