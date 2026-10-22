# FINCO Design — Iteration 10 browser acceptance

Date: 2026-10-20. Scope: only the isolated `GoldenNiceConsultant` mockup sandbox. Tests used the running managed Component Preview Server and a Chromium DevTools browser session. This is manual browser evidence, not a Playwright suite or a production test.

## Workstream 0 — prior Iteration 9 closeout

**Verdict: PARTIAL, not a fully accepted end-to-end release.** `COVERAGE.md` contains substantial Iteration 9 code and browser evidence, including the three screen widths, workbook grids, PPA/facility controls, statement sheets and trace navigation. The original session helper still had one global key for all projects, however, which allowed one sample’s draft state to be reused in another sample. That context-collision risk is corrected in this iteration and the scoped behavior is now browser-tested. The complete component integration map was also added in this iteration. The preview still has no automated test runner, backend, persistence or engine, so it should not be treated as a production acceptance.

## Iteration 10 workstreams

| Workstream | Result | Verified evidence |
|---|---|---|
| A — Project journeys and context | **PASS for the tested demo path; broader coverage PARTIAL** | Clicked Adriatic Solar I, North Ridge Wind and Vela Storage from the Library. The Workspace showed the corresponding project name, ID and technology. Vela showed the preview-only BESS gate. Edited and saved Wind capacity and PPA-B counterparty; Solar retained its own values under a distinct session key. Both projects still use shared synthetic seed assumptions and fixed shared Results. |
| B — Excel productivity and accessibility | **PASS for tested interactions; broad acceptance PARTIAL** | Real keyboard editing of the Hybrid Input Grid blocked Save/Run at −2 MW, recovered after correction to 86 MW, then Save and Run stayed distinct and opened fixed `DEMO-FIXED-018` KPIs. On OPEX, F2/Enter editing, Escape cancel, Ctrl+Z undo, 60 quarterly periods and an invalid 2×2 TSV rejection were exercised; the rejection left zero dirty cells. A valid 2×2 paste staged four cells. At 390 px the OPEX table stayed internally scrollable (4,330 px content / 360 px viewport) with no document overflow; sticky period header and metric label remained anchored. CAPEX rendered 18 monthly columns at 390 px, switched to the S-curve design profile, edited/cancelled a cell, and kept its header/metric label sticky inside the table. |
| C — Financial workflow and worksheet consistency | **PARTIAL** | PPA-A Fixed/Indexed/Scheduled selection showed the matching editor controls (indexation or four scheduled marker inputs); fixed mode showed neither. Senior Debt A/B, Junior, SHL and Equity selections changed the editor heading and commitments. Sources & Uses and Credit Review routes opened with non-reconciliation / NOT EVALUATED language. All six statement tabs were clicked and selected; Results panels for Scenario Comparison and Run History opened. Scenarios, Scenario Compare, Run Compare, Sensitivity, Goal Seek, Diagnostics, Trust, Migration and Exports were reachable through navigation. Not every module’s full business flow or every trace/return variant was browser-asserted. |
| D — Project state, Save/Run and navigation | **PASS for tested paths; full restoration PARTIAL** | A validation error visibly blocked Save and Run; after correction, Save showed a local demo acknowledgment and Run opened the fixed reference values without recalculating them. Browser Back/Forward between Hybrid Input Grid and Revenue changed the active sheet while retaining `PRJ-0236`; workspace focus returned to the workbook and scroll position was 794 px in the tested session. |
| E — Integration handoff | **PASS as documentation only** | `INTEGRATION_READINESS.md` links to the new `UI_COMPONENT_HANDOFF.md` and this acceptance log. The handoff maps mockup components to canonical FINCO concepts, compares Jinja/HTMX, selective React islands and full React, and recommends a narrow one-input CAS-save plus persisted read-only statement PoC. Production endpoints and server contracts are marked TBD; no integration was attempted. |
| F — Build and browser acceptance | **PARTIAL** | TypeScript typecheck and production Vite build passed. Browser tests were manual and broad but not exhaustive; there is no project test script. Project Library, Model Workspace and Results each had document widths measured at 1440, 900 and 390 CSS px with no document-level horizontal overflow. Results statement table at 900 px remained internally scrollable with sticky header/first column; OPEX and CAPEX sticky/internal-scroll behavior was checked at 390 px. No console/runtime errors were captured in the exercised interactions. |

## Specific observed values and limits

- `DEMO-FIXED-018` remains a fixed synthetic reference after input edits: Project IRR 7.82%, Equity IRR 12.46%, NPV €8.7m, minimum DSCR 1.25x. These are not recalculated from a changed input.
- The selected Wind sample’s edited scalar and PPA-B draft were stored under `finco-design-demo:v2:PRJ-0236:*`; the Solar sample used `finco-design-demo:v2:PRJ-0241:*`. This is browser `sessionStorage`, not saved model data.
- At 1440/900 px, browser document width was 15 px below the viewport because of the vertical scrollbar; at 390 px it matched the viewport. This is not horizontal overflow.
- The Results sticky-anchor check at 900 px measured the period header and metric label at the scroll-region origin (approximately 1 px); the 390 px OPEX/CAPEX checks measured 0 px offsets.
- `prefers-reduced-motion: reduce` was emulated; clicking Results “Scroll statement periods right” used `behavior: auto`.
- The Storage badge and workspace notice gate display the feature as preview-only. No storage dispatch, degradation, merchant allocation, financial calculations or covenant result is implemented.
- Inspected live screenshots of Project Library at 1440×900, Model Workspace at 900×900, Results & Analysis at 900×1200, and Results & Analysis at 390×844. The Results 900px view showed all four KPIs and the statement controls without a clipped right column; the 390px first viewport stacked the context and result header without document overflow. Screenshot files were temporary verification outputs, not added to the project.

## Remaining unverified or unavailable

- No live engine, financial formulas, reconciliation, authoritative lineage, persisted Run, run creation/history, auth/permissions, user-specific data, API adapter or production feature gates.
- No actual Excel file import/export, workbook formulas, arbitrary Excel clipboard semantics, or cross-session persistence.
- The current data are illustrative fixed fixtures; project identities do not provide fully distinct Solar/Wind model assumptions or results. Multi-contract allocation, merchant residual and debt/sources-and-uses schedules do not recalculate.
- Browser testing did not exhaustively cover every keyboard combination on every grid, screen-reader announcements, 120-period schedules, every trace-back restoration state, all scenario/goal-seek/sensitivity controls, or every canvas frame under every viewport.
- **Design decision:** this is a reviewable design-freeze candidate only, not an accepted production model UI or integration-ready implementation. The highest priority before any integration is a repeatable automated browser regression suite plus a narrow, independently reviewed canonical-save/Last-Run PoC outside this sandbox.

## Iteration 10 — fresh acceptance closure (2026-10-20)

**Design acceptance: GO for the next design gate; Iteration 11 was not started.** All mandatory P0 demo interactions below passed in an actual Chromium browser session, and the fresh sandbox typecheck/build passed. This is a design-only acceptance, not production approval or a claim of financial-model correctness.

### Fresh build and browser evidence

- `pnpm --filter @workspace/mockup-sandbox run typecheck` — **PASS**.
- `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build` — **PASS** (Vite production build).
- No application source changed during this acceptance pass; the successful build remains applicable. Only this acceptance document was updated.
- Browser method: Chromium DevTools Protocol against the running managed Component Preview Server, with a disposable isolated browser context; actual clicks, keyboard events, browser-dispatched paste events, select changes, wheel scrolling, browser-history navigation and DOM measurements were used. TSV tests dispatched a DOM `ClipboardEvent`; OS clipboard integration and full Excel clipboard behavior were not tested. This was manual browser testing, not Playwright or an automated test suite.

| Acceptance case | Result | Browser evidence |
|---|---|---|
| Canvas frames | **PASS** | Canvas state returned `live` for the original Project Library, Model Workspace and Results & Analysis iframe shapes. Exact live frame URLs are listed below. |
| Library → project → Workspace | **PASS** | Searched and filtered the register, added a local demo row, opened North Ridge Wind and confirmed its project ID/name/technology in Workspace. Then saved Wind capacity as 100, opened Adriatic Solar I (still at its separate 120 seed), and returned to Wind (100 restored). This confirms browser-tab draft scoping for the tested scalar path; all samples still share synthetic seed assumptions and fixed Results. |
| Hybrid Input Grid | **PASS** | Actual Enter/edit, Shift+Enter, Tab/Shift+Tab, Escape cancel, Ctrl+Z undo, valid rectangular TSV, invalid atomic TSV rejection with unchanged values, validation correction, invalid/dirty Run blocking, local Save acknowledgement without Run, and a separate Run opening fixed `DEMO-FIXED-018` values. |
| CAPEX/OPEX period grids | **PASS** | CAPEX showed 18 monthly periods; OPEX showed 12 editable quarters and six separate locked semiannual references. Inline edit/cancel and actual horizontal/vertical wheel scrolling were exercised. Sticky period header and metric label remained anchored during scroll at desktop widths; OPEX sticky/internal-scroll behavior also passed at 390 px. The semiannual view disclosed that it does not aggregate quarters. |
| PPA and facilities | **PASS** | PPA-A/B/C retained separate edited local values when switching records; Fixed/Indexed/Scheduled displayed mode-specific editors. Senior A, Senior B, Junior/Mezzanine, SHL and Equity showed separate commitments after switching. Sources & Uses remained explicitly unreconciled; lender review remained `NOT EVALUATED`. |
| Six financial statement sheets | **PASS** | Clicked P&L, Balance Sheet, Cash Flow, CFADS, Debt Schedule and Sponsor Returns; switched annual/model periods and debt facility; opened a Revenue source-navigation trace and returned to the selected P&L/model-period view. Horizontal statement scroll returned to 178 px after the trace trip. At 390 px, the statement scroller measured 889 px content in a 335 px viewport; after actual wheel scroll the sticky header and metric label were each 1 px from their anchors, with no document overflow. The trace explicitly said calculation lineage is unavailable. |
| Scenarios and delivery panels | **PASS** | Navigated to Scenarios, Scenario Compare, Run Compare, Sensitivity, Goal Seek, Run History, Diagnostics, Trust, Excel Migration and Exports. Scenario Comparison and Run History panels opened; unavailable file and solver workflows remained visibly gated/preview-only. |
| Back/Forward and output truth | **PASS** | Used browser-history navigation between Workspace and Results while retaining the selected Wind identity. The context panel continued to distinguish browser-session Working Copy, fixed `DEMO-FIXED-018`, unknown/unconnected engine and `NOT EVALUATED` integrity. Inputs did not recalculate the fixed illustrative outputs. |
| Responsive layout/actions | **PASS** | Library, Workspace and Results were measured at 1440, 900 and 390 CSS px: no document-level horizontal overflow and primary actions stayed within the viewport. Results at 390 px showed the stacked project/context and KPI layout without page-level crop. This does not mean every interaction was repeated at all nine screen/width combinations. |
| Browser errors | **PASS with dev-preview note** | No `Runtime.exceptionThrown` events or application console errors were captured. Two Vite dev-socket messages said the page entered Back-Forward Cache during browser Back/Forward; these were preview HMR socket messages, not application exceptions. |

### Canvas previews and screenshots

Canvas currently reports these three FINCO frames as live:

- Project Library (`finco-library`): https://f1984df9-8f8a-4156-8384-9b29f33a7fc6-00-1gx2ljbxmk8c2.archer.replit.dev/__mockup/preview/finco-model/ProjectLibrary
- Model Workspace (`finco-workspace`): https://f1984df9-8f8a-4156-8384-9b29f33a7fc6-00-1gx2ljbxmk8c2.archer.replit.dev/__mockup/preview/finco-model/ModelWorkspace
- Results & Analysis (`finco-results`): https://f1984df9-8f8a-4156-8384-9b29f33a7fc6-00-1gx2ljbxmk8c2.archer.replit.dev/__mockup/preview/finco-model/ResultsAnalysis

Canvas also contains one generic default artifact preview; it is not a fourth FINCO screen. The frame URLs were read from live Canvas state; unauthenticated public access was not tested.

Actual screenshots were captured and inspected during the browser run. They remain temporary verification files outside the project (not committed or registered as public assets): `/tmp/finco-i10-library-1440.png`, `/tmp/finco-i10-workspace-390.png`, `/tmp/finco-i10-results-390.png`, `/tmp/finco-i10-opex-390.png`, and `/tmp/finco-i10-results-after-demo-run.png`.

### Gate and limits

- **P0 blocking design defect found:** none in the tested acceptance paths. An initial assertion expected a post-Save edit to remain dirty, but the browser session did not register that test input as a new staged change; its precise cause was not established. The acceptance sequence was narrowed to test dirty-Run blocking before Save, then confirm Save leaves `NOT RUN` before a separate explicit Run. That actual browser sequence passed.
- **Iteration 9 closeout:** the earlier project-context collision concern did not reproduce after the existing project-scoped demo state was exercised. The broader Iteration 9 scope remains a design-only partial relative to production: there is no backend, persistence, engine, full model schema or automated suite.
- **Not accepted as production functionality:** formulas, financial reconciliation, canonical persistence/CAS, live Run, authoritative statement lineage, covenant/integrity decisions, real Excel import/export, authentication and independently calculated project/scenario outputs remain unavailable.
- Current status: no source-code correction was required; no other files were changed in this acceptance pass. Original FincoProtocol, GitHub, backend, database, CI, staging, production and deployment remain outside this sandbox scope.

## Iteration 11 — design-freeze verification (2026-10-20)

**Design Freeze: READY for design review and a separately authorized architecture-discovery task only.** This does not certify financial behavior or authorize production integration. The Iteration 10 browser evidence above remains the actual interaction evidence; no UI behavior changed in Iteration 11, so browser clicks were not repeated.

- Fresh `pnpm --filter @workspace/mockup-sandbox run typecheck` — **PASS**.
- Fresh `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build` — **PASS**.
- `git diff --check` on the handoff/acceptance documentation — **PASS**.
- Canvas state was re-read: `finco-library` ProjectLibrary, `finco-workspace` ModelWorkspace and `finco-results` ResultsAnalysis each reported **live**. The generic default artifact iframe is not a fourth FINCO frame. Preview URLs are those listed above; unauthenticated public access remains unverified.
- No new screenshot or real browser interaction was captured in this docs-only freeze pass. The 1440/900/390 interaction and layout results above are from the earlier actual Chromium acceptance, not a new retest.
- The build regenerated `src/.generated/mockup-components.ts` with only a different ordering of the same four existing preview imports; Canvas still has three FINCO frame shapes. No React/TSX/CSS component or financial output changed.
- `COVERAGE.md` remains the module-state and top-ten-gap inventory. `UI_COMPONENT_HANDOFF.md` now contains the source-verified props/state/component map and copy-ready PoC prompt; `INTEGRATION_READINESS.md` is the index and architecture decision gate. No GitHub, original FincoProtocol app, backend, database, CI, staging or production surface was accessed or changed.
