# FINCO Design harvest manifest — Iteration 15

This describes reusable **design source**, not verified production contracts. Future destination: one full React + TypeScript + Vite frontend, with a separate Python/FastAPI API backend. Existing Jinja2/HTMX remains a legacy reference until parity and an explicit migration decision. All business identifiers, endpoint shapes, permissions, CSRF handling, CAS versions, and server DTOs are `NEEDS_GITHUB_VERIFICATION`.

## Route and component map

| Future React route / area | Current source and exports | Ownership, styling, keyboard | Harvest assessment |
| --- | --- | --- | --- |
| `/projects` | `src/components/mockups/finco-model/ProjectLibrary.tsx` — default `ProjectLibrary` | Owns sample/reference list UI and calls shared session-only copy registry; uses URL navigation and `_group.css`. Keyboard-accessible controls, but no durable project persistence or real authorization. | **WITH ADAPTER** — preserve layout; replace fixtures, session registry, and location navigation with typed project/context interfaces and router. |
| `/projects/:id/workbook` shell | `ModelWorkspace.tsx`, `_shared/FincoShell.tsx`, `_shared/demoSession.ts`, `_shared/demoWorkingCopies.ts`, `_workbook/WorkbookNavigation.tsx`, `_workbook/catalog.ts` | Workspace owns workbook module routing/context and local working/saved state. Shared shell reads URL and sessionStorage; navigation currently uses browser location. Styles: `_group.css`, `_workbook/workbook.css`, `workflows.css`. | **REFACTOR** — retain shell and visual hierarchy; inject a typed project/scenario context and route adapter rather than using global URL/session state. |
| `/projects/:id/inputs` | `_workbook/InputGrid.tsx` — default `InputGrid`, exported `InputGridProps`; `_workbook/gridPaste.ts` | Controlled `values`, `committed`, validation, callbacks, blocked/dirty/readOnly props; grid owns active/editing cell, undo stack and keyboard/paste interaction. Style in `workbook.css`. Enter, Shift+Enter, Tab, arrows, Esc, F2, undo, local bounded TSV are demo behaviors. | **DIRECT REUSE of presentation after boundary hardening** — keep keyboard UI; map to verified canonical field registry and save/validation contract. Prop type is not a production DTO. |
| `/projects/:id/revenue` | `_workbook/RevenueWorkspace.tsx` | Owns PPA-A/B/C session drafts, selectors and local Save; communicates dirty/selected contract through callbacks. Style in `workflows.css`. | **WITH ADAPTER** — retain editor pattern; route, contract identity, validation and Save semantics need typed full-app state and verified server mapping. |
| `/projects/:id/capex` and `/opex` | `_workbook/CostLinePlanner.tsx` — default export, `CostLinePlannerProps`, `LineSheet`, `LineValues`; `_workbook/periodGrid.ts` | Parent controls values/committed/callbacks; planner owns period view, selection, ranges, local undo, validation and keyboard paste. Styles: `period-grid.css`, `workflows.css`. | **DIRECT REUSE of presentation after boundary hardening** — keep demo paste local; do not assume production supports a generic period-cell or atomic multi-row write. |
| `/projects/:id/financing` | `_workbook/FinanceWorkspace.tsx`, `_workbook/CreditDecisionWorkspace.tsx` | Facility drafts/local saves and selection remain within the demo session; Credit is fixed synthetic review. Styles in `workflows.css`. | **WITH ADAPTER / VISUAL ONLY** — forms and register can be harvested; debt sizing, DSCR, reserves and lender decisions must be supplied by canonical services and may not be inferred. |
| `/projects/:id/statements/:sheet` | `_workbook/StatementWorkbook.tsx`, `_workbook/statements.css`; typed contract in `_workbook/statementContract.ts` | Read-only period rows, expanded groups, period/unit controls, synthetic trace navigation and facility display. URL owns selected sheet/period/trace restoration; figures are fixed examples. | **REFACTOR** — typed snapshot props permit fixture injection; move fixture ownership to a separate provider before production reuse. Trace is navigation, not verified lineage. |
| `/projects/:id/results` | `ResultsAnalysis.tsx`, `ResultsAnalysis.css` | Fixed synthetic IRR/NPV/DSCR/chart/history values; local panels and browser URL context. | **WITH ADAPTER** — preserve layout only after a read-only persisted Run projection is verified; no client calculation. |
| `/projects/:id/analysis` | `_workbook/ScenarioGovernanceWorkspace.tsx`, `_workbook/DecisionAnalysisWorkspace.tsx` | Scenario draft UI is session-local; compare/sensitivity/Goal Seek examples are fixed or gated. | **VISUAL / REBUILD behavior** — route layouts may transfer, but real scenario/run identities and sensitivity/solver are absent. |
| `/projects/:id/trust` | `_workbook/ModelDeliveryWorkspace.tsx`, `_workbook/ModuleSurface.tsx` | Trust, diagnostics, history, migration/export and vertical gates are disclosure/example UI. | **VISUAL / GATED** — re-evaluate against server authority and feature gates; import/export and vertical engines are not present. |
| App composition / theme | `src/App.tsx`, `src/main.tsx`, `_shared/FincoApplicationComposition.tsx`, `src/index.css`, `src/components/mockups/finco-model/_group.css` | The internal composition proof lazily imports the same three page exports under one React root; the normal preview renderer still mounts each Canvas screen separately. Shared theme and page CSS are reusable but currently live in the component-gallery workspace. | **WITH ADAPTER** — reuse source components in one full React route tree; remove mockup gallery and preview plumbing only in the separately authorized migration. The composition proof is not a production shell. |

## Dependency and state boundaries

- **Directly controlled presentation boundaries:** `InputGridProps` and `CostLinePlannerProps`. Parent supplies draft/committed values and save/change callbacks; grid owns cell focus/edit mechanics.
- **Fixture/session-coupled components:** `ProjectLibrary`, `FincoShell`, `ModelWorkspace`, `RevenueWorkspace`, `FinanceWorkspace`, `ScenarioGovernanceWorkspace`, `ResultsAnalysis`, `StatementWorkbook`. They read URL and/or sessionStorage and use fixed demo data; do not interpret these IDs or values as server authority. `StatementWorkbook` accepts optional typed `snapshot` and `status` props, but still uses its embedded fixed fixture by default.
- **Mock provider:** `_shared/demoAdapter.ts` and `scripts/demoAdapter.test.mjs` are a fake transport state-transition contract only. No HTTP call, auth, endpoint, production DTO or security control exists.
- **Presentation CSS:** `src/index.css`; `src/components/mockups/finco-model/_group.css`; `_workbook/workbook.css`, `period-grid.css`, `statements.css`, `workflows.css`; `ResultsAnalysis.css`. Reuse tokens and component styles selectively; check font and global selector collisions in a standalone application.
- **Keyboard/test utilities:** `_workbook/gridPaste.ts`, `_workbook/periodGrid.ts`, `_workbook/statementContract.ts`, `_shared/validation.ts`; `scripts/finco-browser-smoke.mjs`, `scripts/periodGrid.test.mjs`, `scripts/statementContract.test.mjs`, `scripts/demoAdapter.test.mjs`, `_shared/demoWorkingCopies.test.mjs`.

## Future server obligations — all require source verification

1. Project identity, ownership, protected Reference access and durable Working Copy creation.
2. Canonical input/contract/facility identifiers and per-scenario ownership.
3. Server validation, same-origin authentication, CSRF, authorization and safe error responses.
4. Version/CAS behavior for scalar batches and the distinct cost-line writer; preserve typed drafts on conflicts and never blind-retry.
5. Explicit user-triggered Run and persisted Last Run projection; no Save-triggered Run.
6. Current/stale freshness, immutable Run identity, engine version and integrity provenance as separate states.
7. Statement period/unit/row schema and verified source lineage; UI trace links alone are not lineage.
8. Feature flags and release availability for import/export, advanced finance and technology modules.

No endpoint, HTTP method, DTO, auth token, feature flag, field ID or exact server contract is asserted by this manifest. These remain `NEEDS_GITHUB_VERIFICATION`.

## Iteration 15 harvest evidence

- `FincoApplicationComposition.tsx` plus the browser case `full React root composes the existing three FINCO pages` proves source-level composition of current exports under one React root. It does not include the gallery, production router, API or auth. Normal Canvas registrations remain exactly the existing ProjectLibrary, ModelWorkspace and ResultsAnalysis frames.
- `StatementWorkbook` receives optional `StatementWorkbookProps` (`snapshot`, `status`, `onSheetChange`) using `StatementWorkbookSnapshot`, `StatementRunStatus`, and `StatementRow` from `_workbook/statementContract.ts`. The fixed fixture stays in the component, so harvesting it still requires a provider extraction.
- Fresh checks: `typecheck`; `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build`; `test:browser` **18/18**; `test:working-copies` **3/3**; `test:demo-adapter` **12/12**; `test:period-grid` **9/9**; `test:statement-contract` **2/2**. These verify the isolated sandbox only.
- Cross-copy browser coverage checked all three PPA and five facility records between two session-only copies plus the Reference baseline; it does not imply backend persistence or independent financial outputs. Full axe/screen-reader/WCAG and OS clipboard remain untested.

## Iteration 16 — standalone transfer manifest

### Entry and route files

- `index.transfer.html` → `src/finco-transfer/main.tsx` mounts `FincoTransferApp` under one React root and imports the existing `src/index.css`.
- `src/finco-transfer/App.tsx` lazily imports the real `ProjectLibrary`, `ModelWorkspace` and `ResultsAnalysis` exports; it provides a single React-owned route tree, `Suspense` loading state, explicit unavailable route and error boundary. No HTML/HTMX islands are used in this transfer entry.
- `src/finco-transfer/routes.ts` owns typed route IDs, preview aliases, canonical transfer paths and route context parsing. `context.tsx` defines typed project/scenario/contract/facility/provider state. These are sandbox navigation contracts, not FINCO API contracts.
- `src/finco-transfer/fixtures.ts` supplies the six-sheet fixed synthetic statement snapshot and status. `ResultsAnalysisProps` passes them down to `StatementWorkbook`; the UI still discloses unknown engine/integrity and never recalculates these figures.
- `src/components/mockups/finco-model/_shared/demoProjectFixtures.ts` owns the default Reference project fixtures. `ProjectLibraryProps` permits caller-supplied project lists/navigation while preserving the existing preview defaults.
- `_shared/viewModels.ts` provides UI-view-model types. PPA/facility view-models are preparatory and are not yet the source of truth for the current editors.
- `_shared/FincoShell.tsx` exposes a dynamic preview/transfer base-path helper and an optional navigation bridge so one component tree can work in its existing preview and standalone test entry. The bridge falls back to ordinary navigation when the transfer shell is not mounted.

### Reuse classification

| Area | Harvest decision | State and follow-up boundary |
| --- | --- | --- |
| Project Library | **DIRECT REUSE + WITH ADAPTER** | Same page component. Default references are separated into a fixture module; parent can pass project records. Working-copy behavior remains browser-session demo state. |
| Model Workspace / Input Grid | **DIRECT REUSE for UI; REFACTOR for product** | `InputGridProps` is controlled and typed; grid owns focus/edit/undo, parent owns current session drafts. Workspace still owns page/session/URL context and demo save/run semantics. |
| Revenue/PPA and Financing | **REFACTOR** | Existing pages support interactive local selectors/editors. New `PpaDraftViewModel` / `FacilityDraftViewModel` types are not connected as provider contracts. |
| CAPEX/OPEX period planner | **DIRECT REUSE for demo; REFACTOR for canonical writes** | `CostLinePlannerProps` is typed/controlled; period-grid TSV is client-local all-or-nothing demo behavior. Preserve verified production row/batch write granularity only after GitHub audit. |
| Results and six statements | **DIRECT REUSE + WITH ADAPTER** | `ResultsAnalysisProps` and `StatementWorkbookProps` accept external snapshot/status. Transfer supplies fixed synthetic rows; existing fallback, URL/trace/period state remain. |
| Diagnostics, Trust, scenario/history, credit, gated modules | **DIRECT REUSE for visual/demo surfaces; REBUILD for production authority** | Current interactions are sample-only or explicitly gated. No live engine state, credit decision, import/export or feature-gate authority. |
| API, auth, CAS, canonical save/Run, persisted results | **REBUILD / NEEDS_GITHUB_VERIFICATION** | No production service contract is known or implemented in this sandbox. |

### Build, verification and source package

- `pnpm --filter @workspace/mockup-sandbox run typecheck` — PASS.
- `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build` — PASS.
- `BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build:transfer` — PASS.
- Browser smoke: **19/19 PASS**. Unit suites: **31/31 PASS** across adapter, working-copy, period-grid, statement-contract and transfer-route tests. See `BROWSER_ACCEPTANCE.md`.
- Source archive manifest and exact contents: `FINCO_REACT_TRANSFER_RC1_REPORT.md`; source-only ZIP: `generated-artifacts/finco-react-transfer-rc1.zip`.
- Verified build dependency set in this sandbox: React 19.1.0, React DOM 19.1.0, Vite 7.3.6, `@vitejs/plugin-react` 5.2.0, and `@tailwindcss/vite` 4.3.3. Workspace catalog aliases are not a portable lockfile; reconcile versions in the destination React app.
- Canvas registration remains exactly the three original FINCO frames. The archive omits Canvas and preview registration/config so the migration agent can import the reusable component tree into its own full React app.

All endpoints, auth/CSRF/permissions, canonical field names, validation, CAS, persisted Last Run, engine version, financial integrity and release gates remain `NEEDS_GITHUB_VERIFICATION`.

## Iteration 17 — RC2 portability and browser evidence

- RC1 remains frozen at its original path and checksum; RC2 is a separate package that overlays the current source/docs and places the exact standalone files from `transfer-support/` at the package root (`package.json`, `pnpm-lock.yaml`, `tsconfig.json`).
- Verified toolchain: Node `24.12.0`, pnpm `10.26.1`, React/React DOM `19.1.0`, Vite `7.3.6`, `@vitejs/plugin-react` `5.2.0`, Tailwind/Tailwind Vite plugin `4.3.3`, TypeScript `5.9.3`. Use `pnpm install --frozen-lockfile`, `pnpm run typecheck`, `pnpm run build:transfer`, and `pnpm run test:unit`.
- The clean extracted RC2 package passed install/typecheck/build. A temporary local static Vite preview passed real Chromium checks for assets, MIME, direct route/reload, Back/Forward, three pages, and 1440/900/390 layouts. Browser evidence is recorded in `BROWSER_ACCEPTANCE.md`; it is not a production deployment.
- Final Iteration 17 test evidence: browser 19/19; isolated unit suites 34/34. Full axe, screen-reader/WCAG, and OS clipboard checks remain untested.
- Component ownership and all real production contracts are unchanged. Backend API/DTOs, canonical validation/CAS, permissions, CSRF, persistence, Run and release gates remain `NEEDS_GITHUB_VERIFICATION`.

## Iteration 19 Correction A — keyboard/source delta

- `StatementWorkbook` now exposes one roving period-value Tab stop, keyboard instructions and focus restoration to the selected cell after returning from a synthetic trace. The helper is isolated in `statementContract.ts` with a unit test.
- Existing typed snapshot/status and editor props remain the reuse seams. Fixture/session ownership was not broadly refactored; visible statement values remain fixed synthetic examples.
- Latest test record and source archive status: `FINCO_REACT_I18_CORRECTION_A_I19_REPORT.md`; browser results: `generated-artifacts/i19-correction-evidence/i19-full-suite-browser-results.json`.
