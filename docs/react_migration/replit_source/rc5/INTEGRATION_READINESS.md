# FINCO Design integration readiness — Iteration 15

## Iteration 20 provider boundary addendum

The statement table now has a clean UI-level boundary: `StatementWorkbook` receives typed snapshot/status props and does not own demo rows. `ResultsAnalysisView` is the reusable page; the existing Canvas `ResultsAnalysis.tsx` wrapper supplies a fixed synthetic fixture, while `src/finco-transfer/App.tsx` imports the view directly and supplies the independent transfer fixture. Explicit `null` yields “unavailable,” not sample fallback. The built transfer JS was verified not to contain Canvas-only statement-row fixture markers. This is source/build separation only; it does not establish production DTO compatibility, persistence, financial parity, or Run provenance. Exact backend contracts remain `NEEDS_GITHUB_VERIFICATION`.

Iteration 20 fresh evidence: typecheck and Design/transfer builds passed; unit tests 39/39 passed; the source-only RC4 archive passed clean extraction, frozen install, typecheck, transfer build and unit tests; Chromium 22/24 passed, 0 failed, 2 untested (axe and Firefox/WebKit). Existing preview routes remained live. Details are in `BROWSER_ACCEPTANCE.md` and `FINCO_STATEMENT_PROVIDER_I20_REPORT.md`.

## Owner architecture decision (supersedes prior option ranking)

The selected long-term target is a **complete React + TypeScript + Vite frontend** with a separate Python/FastAPI API backend. The existing Jinja2/HTMX application remains the legacy reference until the new frontend reaches agreed parity; this Design project does not implement that migration. The earlier recommendation to evaluate permanent React islands is superseded. Islands may be used only as a temporary, explicitly approved migration step, not as the target architecture.

The sandbox components below are harvest candidates, not production-ready drop-ins. A separate GitHub Architecture & Contract Audit must verify API and security contracts. No endpoint, API payload, field registry, auth contract, CSRF mechanism, CAS version, or server DTO is asserted here. See `DESIGN_HARVEST_MANIFEST.md` for the source inventory and intended route map.

## Decision summary

The mockup is ready as a **design reference and component-harvest source**, not as an integration-ready production frontend. Keep all current outputs labeled synthetic. Do not connect these components to FINCO until the canonical field registry, server contracts, authorization, save concurrency, and persisted Run projection are independently verified.

Iteration 13 adds a browser-tested **Reference → session-only Working Copy** design journey. This is not a production project-clone contract, persistent copy, authorization rule, or evidence that project-specific outputs exist.

The FINCO architecture details in this section that were included in the task are owner-supplied context, not independently re-read or verified against GitHub during this isolated design iteration. Do not treat them as release or endpoint confirmation.

## Options

| Option | Reuse and fit | Integration risks | Assessment |
| --- | --- | --- | --- |
| **A. Port design into current Jinja2/HTMX shell** | Preserves the existing server-rendered workbook shell and current server ownership. Layout, tokens and interaction patterns can be harvested, but React components cannot be reused directly. | Reimplement dense grid interaction in the existing rendering model; preserve CSRF, field validation, ownership, atomic save and HTMX response behavior. | Valid legacy-maintenance option, but **not the selected long-term target**. |
| **B. Selective React islands** | Retain Jinja2/HTMX as the page and navigation owner; reuse React/TypeScript patterns only for complex grids or high-density editors. | Requires a deliberate mount/unmount contract. HTMX swaps and OOB updates must not replace DOM owned by a mounted React root. One layer must own each region. Server remains authoritative for validation, CAS, permissions, and persisted outputs. | **Superseded as a target.** Consider only as a temporary, separately approved migration bridge if justified by the audited branch. |
| **C. Full React + TypeScript + Vite frontend** | Best alignment with the owner's selected target and the sandbox's React/TSX component tree, workbook interactions and CSS. Enables one route, state, focus and accessibility model. | Requires verified API adapters, auth/CSRF, route/permission parity, validation/CAS, stale/current persisted Run projection, error/loading behavior, exact-head CI, performance and parity testing. Legacy templates remain until verified parity and migration approval. | **Selected target, conditional on architecture audit and a bounded decision PoC.** Harvest presentation and typed boundaries; do not imply the mockup supplies production contracts. |

## Non-negotiable integration boundaries

1. The canonical server remains the authority for input validation, ownership, permissions, save transactions and Run execution.
2. Saving input never implicitly executes a financial Run. Edited inputs mark the persisted Last Run stale; output values remain read-only projections of a persisted Run.
3. Scalar-grid batch save and cost-line save may have different transaction/CAS granularity. Do not equate the demo’s all-or-nothing TSV paste with a production multi-row cost-line write.
4. A concurrency conflict must retain the user’s typed draft and must not silently retry against a new version.
5. CSRF, same-origin authentication and reference/read-only permissions require canonical implementation, not client-only disabled controls.
6. If a temporary HTMX + React island is separately approved, each DOM region must have one owner. Define React mount/unmount cleanup around swaps and OOB refreshes; test double-mount, stale roots, event handlers and focus restoration. This is a migration risk, not the selected end state.
7. Trace navigation in this design is not verified numerical lineage. Production statement tracing must link to the canonical input/result source and preserve Run identity.
8. Production endpoints, payloads, CSRF token location, CAS version fields, response envelopes and current/stale rules are all **NEEDS_GITHUB_VERIFICATION**.
9. Client-side Reference mode and local session-copy IDs are only demonstration affordances. The canonical app must authorize Reference visibility and copy creation, establish ownership and return a trusted working-copy identity; none of that is implemented by this Design project.

## First GitHub Architecture PoC — proposed, not executed

Do this only in a separately authorized task in the canonical repository:

1. Add one existing editable project/input field to a feature-flagged path.
2. Save through the canonical server-side validation and CAS path; preserve typed edits on validation failure or conflict.
3. Show explicit `CURRENT`/`STALE` state against the persisted Last Run. Save does not call Run.
4. Render one existing persisted statement as read-only; do not add calculations or fabricate a result.
5. Keep the existing Jinja2/HTMX page as a legacy fallback until the full React route proves the agreed parity; decide explicitly whether an island is needed only as a temporary bridge.
6. Require exact-head CI, independent read-only code review, normal merge controls, and staging acceptance only after separate user authorization.
7. Define rollback by disabling the feature flag; do not migrate routes or replace the workbook shell in the PoC. The PoC informs the full React architecture decision; it is not approval to permanently adopt islands.

### Required read-only Architecture & Contract Audit before that PoC

In a separate, explicitly authorized GitHub task, inspect the current exact-head canonical source and record citations for the workbook shell, scalar field registry/validator, scalar batch save/CAS/CSRF/ownership, per-row CAPEX/OPEX writer, reference/read-only rules, Run invocation, persisted Last Run projection, freshness/integrity provenance, scenario/history identity, and HTMX OOB update lifecycle. Confirm current tests and feature-gate mechanisms. Do not infer endpoints or DTOs from this mockup. Any item not located in source/tests remains `NEEDS_GITHUB_VERIFICATION`.

### PoC acceptance contract (design proposal only)

- One real existing editable field, on one feature-flagged path, uses canonical server validation and Save/CAS; conflict and validation errors retain the typed value with no blind retry.
- One existing persisted Last Run statement is displayed read-only with the canonical run identity and explicit `CURRENT` or `STALE` state. The Save request does not call Run; no frontend calculation or fabricated output is allowed.
- Existing Jinja2/HTMX page remains the fallback. If an island is tested, its root has a single DOM owner, mounts/unmounts cleanly across HTMX swaps and OOB refreshes, and restores keyboard focus without duplicate listeners or stale roots.
- Same-origin auth, ownership, CSRF, feature-flag denial, auditability, exact-head CI, independent read-only review, rollback behavior, and staging checks are tested/recorded by the authorized production task. Staging requires separate user approval.
- No endpoint name, request/response shape, token location, CAS field, feature flag identifier, or source lineage is supplied by this design document; each must be discovered and verified in canonical source.

No GitHub access, branch, endpoint, production code, database, CI, staging or deployment change was made in Iteration 12.

## Top 10 integration blockers / risks

1. No verified mapping from demo cells to canonical FINCO workbook field IDs.
2. No verified auth, ownership, CSRF, reference/read-only, or feature-gate contract.
3. No real server validation or error-envelope adapter.
4. No actual scalar batch CAS version/token or conflict response contract.
5. Cost-line row writer semantics and multi-row paste policy are not connected to this demo.
6. No persisted Last Run schema, immutable run identity, input-version comparison, or stale/current projection wired to the UI.
7. No verified statement schema, units/period basis, source lineage, or data provenance payload.
8. No canonical scenario/facility/contract persistence identity or isolation contract.
9. No tested React mount/unmount lifecycle with HTMX swaps and OOB responses.
10. No exact-head CI or independent review of a production adapter; no production financial parity or accessibility acceptance.

## Design evidence

See `COVERAGE.md`, `UI_COMPONENT_HANDOFF.md`, and `BROWSER_ACCEPTANCE.md`. Those documents describe the sandbox only. The six statement pages, grid behavior, local Save/Run, scenarios, Trust and gated surfaces remain synthetic or demo-only. Iteration 13 browser evidence includes the Reference/Working Copy UX and explicit gated-state clicks; it does not establish production copy/persistence/security semantics. Current test evidence is `test-evidence/iteration-13-browser-results.json` and `test-evidence/i13-*.png`.

## Iteration 13 readiness decision

- **Design handoff:** READY for a separate read-only canonical source/contract audit and architecture discussion.
- **Production integration / GitHub PoC:** NOT READY to implement from this sandbox alone. First complete the independent source audit above and confirm all security, field, CAS, cost-line, Run, and projection contracts against current code and tests.
- **Preview state:** exactly the three intended FINCO screens are in scope. No fourth FINCO design screen was created.
- **Validation boundary:** the local Reference lock, session-only Working Copy, demo adapter tests, and fixed output states prove only mockup behavior; there is no financial engine, real persistence, actual auth, or production API.

## Iteration 15 full-React harvest evidence

- The I15 browser suite passed **18/18**. It covered one-root composition of the existing three pages, all three preview routes at 1440/900/390, two-copy isolation across PPA-A/B/C and all five facility records, mobile Reference→Working Copy→trace, grid and statement regressions, scenario/history/gated surfaces, and captured console errors. Exact steps and limits are in `BROWSER_ACCEPTANCE.md`.
- `StatementWorkbook` now accepts typed `StatementWorkbookSnapshot` and `StatementRunStatus` props defined in `_workbook/statementContract.ts`. The default fixed fixture and URL presentation state remain component-coupled; this is a partial seam, not a separated data provider.
- `FincoApplicationComposition.tsx` is an internal one-root composition proof using the existing page exports. It is not a production SPA, backend adapter, auth model, or new Canvas preview.
- The Project Library landmark issue is corrected with a named breadcrumb navigation. The smoke suite confirms named navigation and visible-control labels on all three routes; F2/Esc focus recovery is tested. Full axe/screen-reader/WCAG, cross-browser and OS clipboard coverage remain untested.
- I15 updates the route/source/reuse inventory in `DESIGN_HARVEST_MANIFEST.md` and component handoff in `UI_COMPONENT_HANDOFF.md`. No production endpoint, DTO, field ID, auth/CSRF, permission, CAS, or feature-gate behavior was invented; each remains `NEEDS_GITHUB_VERIFICATION`.
- Evidence files are `test-evidence/iteration-15-browser-results.json` and `test-evidence/i15-*.png`. All results remain fixed synthetic demo values. The three intended Canvas frames remain `finco-library`, `finco-workspace`, `finco-results`; no fourth FINCO frame was created.

## Iteration 16 — standalone React transfer assembly

- `src/finco-transfer/` and `index.transfer.html` add a separately buildable React entry that uses the existing Project Library, Model Workspace and Results & Analysis TSX exports. The in-workspace route `/__mockup/finco-transfer/` is a browser-test route, not a new Canvas frame or a production URL.
- `pnpm --filter @workspace/mockup-sandbox run build:transfer` now builds the transfer entry independently of the Design gallery. Fresh standard and transfer builds and TypeScript typecheck passed; the final Chromium suite passed 19/19. Exact evidence is in `BROWSER_ACCEPTANCE.md`.
- The transfer root provides typed route, project/scenario/contract/facility context and a fixed synthetic statement provider. Project Library’s default reference fixtures are separately declared and can be supplied through typed props. The visible transfer UI still uses the pages’ current demo/session behavior; `demoAdapter.ts` remains test-only.
- **Handoff status:** useful for harvesting and validating React composition, but not a drop-in production frontend. Production field IDs, route ownership, DTOs, auth/session, CSRF/ownership, canonical validation, CAS/revision semantics, line-item write granularity, Run authorization, persisted Last Run projection, scenario identity and release gates remain `NEEDS_GITHUB_VERIFICATION`.
- **Readiness decision:** **FULL REACT TRANSFER RC1 READY as an isolated design/source package only.** This does not approve production integration, GitHub changes, staging, financial parity, or deployment. The separate GitHub audit must validate contracts before any implementation.
- Current evidence: `test-evidence/iteration-16-browser-results.json` and `test-evidence/i16-*.png`. Three original Canvas FINCO frames are live; the generic Artifact iframe is separate. An early I16 test attempt overwrote three former I15 evidence paths; see `BROWSER_ACCEPTANCE.md` and use I16 evidence as the current source of truth.

### Current handoff decision

- **Full-React source harvest:** **PARTIAL / useful as a design reference**. Existing page and grid components have been composed under one React root, and `InputGrid`, `CostLinePlanner` and `StatementWorkbook` have typed presentation boundaries. Several pages still own URL/session/fixture state; they are not drop-in production components.
- **Design QA:** PASS for the exercised I15 demo flows and current browser/type/build checks.
- **Production integration readiness:** **NOT READY** until the separate canonical source audit verifies real field IDs, DTOs, auth/CSRF/ownership, save/CAS, cost-line semantics, Last Run projection, scenario identity, and release gates. No production integration or GitHub task was performed here.

## Iteration 14 evidence and remaining boundary

- Fresh sandbox checks for Iteration 14 are recorded in `INTEGRATION_PREP_PROGRESS.md`; browser steps/results are in `BROWSER_ACCEPTANCE.md`, module states in `COVERAGE.md`, and source-specific harvest details in `UI_COMPONENT_HANDOFF.md`.
- The browser-tested two-copy flow demonstrates representative separation of session-local scalar, PPA-A, Senior A, Base scenario, CAPEX and OPEX drafts, including same-tab reload. It does not demonstrate new-tab behavior, server cloning, authorization, durable persistence, complete cross-copy state coverage, or copy-specific financial outputs. Fixed statements/KPIs/history stay shared synthetic fixtures.
- The fake typed adapter has 11 passing unit cases. It models error/status transitions in local tests only; it is not imported by the visible UI and does not define real FINCO endpoints, DTOs, auth, CSRF, permissions, CAS tokens or production response handling.
- `InputGridProps` and `CostLinePlannerProps` are exported component boundaries; broader view/fixture/session ownership remains coupled, especially in `StatementWorkbook`. Consider extraction only after the separate canonical-source audit identifies a real host and lifecycle contract.
- Browser DOM-name checks and an F2/Esc focus-return check are recorded, but no axe, screen-reader, cross-browser or full WCAG evaluation was run. The checklist is `ACCESSIBILITY_MANUAL_CHECKLIST.md`.
- The isolated Design remains a **design-harvest reference only**. All displayed financial output remains synthetic and fixed. No production component, endpoint, database, auth, engine, GitHub or deployment was touched in this phase.

## Iteration 21 — Results view-model seam

- `ResultsAnalysisView.tsx` now requires caller-owned `ResultsPresentationSnapshot | null` plus `ResultsRunStatus`; statement snapshot/status remain explicit props. The reusable view does not import Canvas synthetic fixtures.
- `ResultsAnalysis.tsx` is the isolated Canvas/demo boundary and injects `SYNTHETIC_RESULTS_SNAPSHOT` only for omitted props. Explicit `null` remains unavailable. The transfer route uses a separate `src/finco-transfer/resultsFixtures.ts`; neither provider defines a production DTO.
- The typed contract distinguishes `value` from `unavailable`, and data origin, displayed run state, freshness, engine currency and integrity are separate. The demo `fixed-demo` status must not be represented as a persisted Run.
- The supplied chart geometry and labels are presentation values. They are not calculated from inputs or reconciled to statement rows; do not harvest `syntheticResultsProvider.ts` or `resultsFixtures.ts` into production.
- Browser evidence: 22/24 PASS, 1 PARTIAL (axe scroll-region finding), 0 FAIL, 1 UNTESTED (Firefox/WebKit). Unit results: 45/45; final TypeScript/build evidence and screenshot paths are in `BROWSER_ACCEPTANCE.md`.
- Real results DTOs, statement schemas, run identity, freshness semantics, engine version, integrity provenance, permission gates and route contracts remain `NEEDS_GITHUB_VERIFICATION`. No endpoint or API behavior was inferred in this iteration.

## Iteration 17 RC2 addendum — standalone harvest and cross-copy evidence

- `transfer-support/package.json`, `transfer-support/pnpm-lock.yaml`, and `transfer-support/tsconfig.json` now provide an independent, exact-version package definition for the exported React/Vite source. The clean extracted package installed, typechecked, and built; it can be served locally with SPA fallback and same-origin direct-route support. This verifies packaging mechanics only.
- The final Chromium/CDP run passed 19/19. It exercised the served build at 1440/900/390, direct deep link/reload, Back/Forward, reference-to-copy creation and two-copy project/scenario/contract/facility/cost-grid isolation. Evidence is in `BROWSER_ACCEPTANCE.md`.
- The isolated fake adapter now models project-context mismatch, concurrent typed edits while Save is pending, independent selected Run/engine-currency/integrity fields, and zero versus unavailable. Its 15 passing cases are unit tests only; the adapter is not a live transport or production DTO contract.
- The three original Canvas frames remain the only FINCO previews. RC1 was kept frozen; RC2 is a separate source-only package.
- **Still NEEDS_GITHUB_VERIFICATION:** canonical field IDs and DTOs, auth/CSRF/session behavior, real scalar/cost-line CAS limits and response semantics, persistence of project/scenario/contract/facility state, stale/current Last Run projection, HTMX replacement lifecycle, exact production React branch/build conventions, and any release gates. No endpoints or adapter compatibility are asserted here.
- **Accessibility remains partial:** named navigation landmarks and selected keyboard/focus behavior passed; no axe, screen-reader, full WCAG, or OS clipboard validation was performed.

### Iteration 18 QA status

The initial I18 sandbox browser run was **20/24 PASS, 2 FAIL, 2 UNTESTED**. The additive I19 correction reproduced both failures, found the copy-grid failure was an opaque-origin test setup issue, and fixed the statement table's excessive Tab stops plus trace-return focus restoration. The fresh full Chromium suite is **22 PASS, 0 FAIL, 2 UNTESTED**; fresh typecheck, design build, transfer build and **35/35** unit checks pass. Axe and Firefox/WebKit remain untested because tooling is unavailable; this is not full WCAG or cross-browser acceptance. See `FINCO_REACT_I18_CORRECTION_A_I19_REPORT.md` for the transfer package disposition. Production contracts remain `NEEDS_GITHUB_VERIFICATION`; no GitHub/API integration is authorized or implied.

### Iteration 22 handoff addendum

- **Design-only components added/refined:** `_shared/SourceAuthorityDrawer.tsx` and its stylesheet provide a reusable local disclosure for current PPA, CAPEX/OPEX line-period and financing selections. `CreditDecisionWorkspace` now links a selected synthetic facility/period observation to the debt statement and restores context on return. `DecisionAnalysisWorkspace`, `ScenarioGovernanceWorkspace`, `ResultsAnalysisView` and the PPA/cost/financing editors show explicit scenario/Run/freshness/engine/integrity dimensions and local-draft authority without calculations.
- **Axe correction:** the protected Reference form no longer disables the Input Grid scroll region itself; the grid remains inspectable by keyboard while its own read-only cell guards remain authoritative. Workbook row-number contrast was raised. The final axe scan had no violations in the three tested views; it is not a full WCAG result.
- **Production boundary unchanged:** all new observations, IDs and source labels are synthetic or conceptual. No endpoint, DTO, permission, CAS, financial lineage, persisted Run or API adapter is claimed. These mappings remain `NEEDS_GITHUB_VERIFICATION`.
- **Latest evidence:** full Chromium **27/28 PASS / 0 FAIL / 1 UNTESTED**, six unit suites **45/45**, fresh typecheck and Design/transfer builds PASS. Firefox/WebKit are unavailable; full screen-reader/WCAG remains untested. The local static transfer build was served at `127.0.0.1:4174` only.
- See `FINCO_RESULTS_WORKBOOK_I22_REPORT.md` and `RC5_TO_RC6_MANIFEST.md` for exact changed source files, QA scope, and RC6 package contents. This design-only evidence is not a production integration gate.

### Iteration 23 — result-state and comparison presentation addendum

- `ResultsRunStatus.productContext` is optional UI-only metadata for the isolated transfer harness: reference/working-copy mode, local draft state, working scenario ID, displayed Last Run scenario/timestamp, and a scripted failed-attempt note. These names and status transitions are not verified canonical FINCO DTO fields.
- `src/finco-transfer/productStates.ts` supplies fixed synthetic state examples. The selector is present only in the standalone transfer QA harness. It does not create a server-side working copy, save, Run, status update, or authorization decision.
- `src/components/mockups/finco-model/_results/runComparisonFixtures.ts` contains independent fixed period labels and display values for the current design’s three sample Run references. `DecisionAnalysisWorkspace` renders each Run on its own calendar. It performs no frequency conversion, date/index alignment, aggregation, DSCR calculation, or statement reconciliation.
- Scenario Compare explicitly reports missing period basis/date coverage instead of implying that scenario rows share a comparable period set. Missing metrics render unavailable, not zero.
- **Production contract remains NEEDS_GITHUB_VERIFICATION:** real project/scenario/run identity, canonical freshness and engine-currency meanings, Last Run projection, status persistence, period schemas/basis, per-period null semantics, permissions, and any failure handling must be derived from the separately authorized canonical FINCO source audit. Do not port the synthetic state selector/provider into the production React app.
- I23 fresh verification: unit suites 47/47; typecheck, Design Vite build, transfer build and scoped diff check PASS; Chromium 29/30 PASS with the sole UNTESTED case Firefox/WebKit. Axe reports no violations on the three scanned Canvas states but has incomplete checks and is not a WCAG certification. Exact steps and evidence are in `BROWSER_ACCEPTANCE.md` and `FINCO_I23_PRODUCT_STATE_REPORT.md`.
- RC7 is an isolated source-only delta intended for review after RC5 then RC6. It is not merged into GitHub PR #339 and does not authorize production use. No generated Canvas preview registry change is included in the final I23 diff or transfer overlay.
