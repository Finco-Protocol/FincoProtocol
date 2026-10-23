# FINCO UI component handoff — design only

## Scope and evidence boundary

This handoff describes the isolated `GoldenNiceConsultant` prototype and compares it with the FINCO concepts supplied by the owner. The original application, its Jinja2/HTMX templates, server routes, workbook registry, validation, persistence, RuntimeResult schema, authentication, and CI were not inspected. Every production mapping below is therefore a **candidate interface to verify**, not a claim that an endpoint, class, payload, or feature currently exists. See [`COVERAGE.md`](./COVERAGE.md) for module status and [`BROWSER_ACCEPTANCE.md`](./BROWSER_ACCEPTANCE.md) for tested versus untested behavior.

The sandbox has no API, backend, database, engine, user authentication, or durable model storage. All editable state is browser-tab demo state; all output, scenario, credit, history, and trace values are synthetic and fixed.

## Component-to-concept map

| Design component | Current prototype behavior | FINCO concept to verify with owners | Required production boundary; all TBD |
|---|---|---|---|
| `ProjectLibrary.tsx`, `_shared/FincoShell.tsx`, `_group.css` | Synthetic register, project context in query string, preview-only storage gate, scoped browser-tab demo drafts | Jinja2/HTMX portfolio shell and canonical project/model identity | Project lookup, access policy, project-to-Working-Copy mapping, released capability flags; route and schema TBD |
| `ModelWorkspace.tsx`, `_workbook/InputGrid.tsx`, `_shared/validation.ts`, `_workbook/gridPaste.ts` | 21 example scalar fields, client validation, keyboard editing, atomic demo TSV paste, local Save/Run separation | Workbook field registry, server validation, canonical Working Copy save | Stable field/period IDs, units, edit permission, expected revision, authoritative validation and atomic CAS save; API and conflict response TBD |
| `_workbook/RevenueWorkspace.tsx` | PPA-A/B/C local drafts with Fixed/Indexed/Scheduled editors | Multi-contract Revenue/PPA contract registry and allocation authority | Contract identity, time basis, allocation, overlap, merchant residual, index and schedule validation; source and write contracts TBD |
| `_workbook/CostLinePlanner.tsx`, `_workbook/periodGrid.ts` | CAPEX/OPEX focused period grids, keyboard/range/TSV checks, independent local line saves | Canonical cost-line row writer and project period calendar | Stable line/period identity, allowed units, atomic row-batch validation, revision check and conflict handling; writer API TBD |
| `_workbook/FinanceWorkspace.tsx` | Five separate local facility drafts; static Sources & Uses/reserve snapshots | Facility register, equity/investor records, Sources & Uses and debt schedules | Canonical facility/source/use IDs, transaction ordering, permissions and authoritative reconciliation; data contracts TBD |
| `_workbook/TimelineTaxWorkspace.tsx` | Local date, tax and timing examples | Project timeline and tax input registry | Jurisdiction, tax basis, depreciation and period conventions; canonical validation and write authority TBD |
| `_workbook/StatementWorkbook.tsx`, `ResultsAnalysis.tsx` | Six fixed statement sheets, display controls, navigational source trace and preset Run identity | Controlled Run command and persisted RuntimeResult/Last Run projections | Read-only projection keyed to persisted Run ID, committed input revision/hash, engine/model version, timestamp and status; statement IDs, units, lineage and endpoint TBD |
| `_workbook/ScenarioGovernanceWorkspace.tsx`, `_workbook/DecisionAnalysisWorkspace.tsx` | Local scenario drafts, fixed compare/sensitivity samples and authored history rows | Scenario store, run comparison, sensitivity/Goal Seek and run ledger | Persisted scenario/run identity, aligned periods and explicit solver/run authority; all schemas and services TBD |
| `_workbook/CreditDecisionWorkspace.tsx` | Fixed lender-review examples and selector-driven display | Credit/lender decision and covenant review | Server-authoritative policy, lender access, evidence, approval states and covenant definitions; all TBD |
| `_workbook/ModelDeliveryWorkspace.tsx` | Trust, migration and export workflow previews | Trust/provenance pack, Excel migration and export | File security, parser/renderer, storage, source evidence, permissions and audit; no file API is inferred |
| `_workbook/WorkbookNavigation.tsx`, `ModuleSurface.tsx`, `catalog.ts` | Client navigation and explicit gated/unavailable destinations | Jinja2/HTMX shell navigation and product capability policy | Server-owned routes, authorization and release gates; client visibility is not authority |
| `_workbook/workbook.css`, `workflows.css`, `period-grid.css`, `statements.css` | Presentation, sticky grids, responsive layout and focus states | No server-side authority; presentation only | Preserve semantic grid/table roles, internal scroll ownership, keyboard/focus behavior and reduced-motion preferences when an approved UI integration is designed |

## Save, Run, stale/current, and AUTH rules

1. Treat the server—not React, HTMX or this prototype—as authority for identity, permissions, feature gates, validation, persistence and output freshness.
2. A production editable field needs a stable field/period identity, unit, value, editability and expected Working Copy revision. Save must validate and commit the whole authorized batch atomically or reject it without partial writes; a revision conflict must not silently overwrite another edit.
3. Save is not Run. A controlled Run may only follow the established production contract and should return persisted evidence bound to the committed input revision/hash, model/engine version, user, timestamp and status.
4. A read-only statement is `CURRENT` only when its persisted Run evidence matches the relevant committed revision. Otherwise display `STALE` or `UNKNOWN`; do not infer freshness from the selected project or URL.
5. Project access, editing, Save, Run, credit approval, Trust, file import/export and technology gates require server-side authorization. A client-side disabled state is not an access-control decision.
6. No direct automatic Run on Save, no guessed routes/payloads, no synthetic green covenant/integrity result, and no formula/financial calculation inferred from a navigation link.

## Production architecture options

| Option | Reuse and lifecycle | Risks | Current assessment |
|---|---|---|---|
| Port to existing Jinja2/HTMX UI | Rebuilds the grid interactions in server templates; uses existing server-rendered ownership if confirmed | Highest interaction duplication; keyboard/paste behavior can diverge | Reasonable only if the owners require a fully server-rendered frontend |
| Selective React islands in existing shell | Reuses the complex React period grids while leaving simple screens in the existing shell | HTMX swaps can leave stale React roots, duplicate DOM ownership, event handlers or unsaved local state unless mount/unmount and state handoff are explicit | **Recommended first PoC, conditionally**, after confirming the actual shell supports islands and owners approve the boundary |
| Full React against existing server | Reuses more prototype UI and offers unified client navigation | Requires broad stable API contracts, auth/session/CSRF and CAS semantics; largest migration, test, security and maintenance surface | Do not choose until a verified API contract and product ownership decision justify it |

## Proposed first GitHub Architecture PoC — not started here

In a separately approved branch/repository, first verify the actual shell, auth/permissions, field registry, save/run contracts and CI. Then prototype exactly:

1. One editable scalar field saved through the canonical server validation and revision/CAS boundary, with atomic conflict handling.
2. One read-only persisted statement row/view sourced from an existing RuntimeResult/Last Run projection, showing Run ID/version and truthful `CURRENT`/`STALE`/`UNKNOWN` state.
3. No auto-Run on Save, no new calculation logic and no guessed endpoint. Require exact-head CI, an independent review, permission/conflict tests and an HTMX lifecycle test if React islands are chosen.

This is a conceptual handoff only. No GitHub, original application, backend or production surface was accessed or changed.

## Source-verified component harvest inventory (2026-10-20)

This section records the actual TypeScript props and browser-state ownership found in the sandbox source. Production equivalents, server contracts, field IDs and release permissions remain **NEEDS_GITHUB_VERIFICATION**. The acceptance references below point to manual Chromium evidence in `BROWSER_ACCEPTANCE.md`, not automated test coverage.

### Project and shell

| Source | Props and state owner | Current data and interaction | Harvest / integration boundary |
|---|---|---|---|
| `ProjectLibrary.tsx` | No component props. Owns React state for search, stage/technology filters, seed/local project rows and the one-row-created flag. | Five fixed sample projects; search/filter and “Create project” are local. “Open model” builds a URL from project identity. BROWSER case: Library → Wind and the Solar/Wind draft-scope check. | Future project records and project-to-Working-Copy mapping must come from the canonical server. Local KPI totals and the new row are not authoritative. Uses `_group.css` and shared shell components. |
| `_shared/FincoShell.tsx` | `ProjectContext` is read from the URL; exported components have small presentation props (`Shell`, `DemoBanner`, `DemoContextStrip`, `ModelNav`, `Status`, `Field`, `Panel`). | Provides breadcrumbs, context, notices, field rendering and route helpers. It does not resolve identity or permissions. | Replace URL-derived identity with approved server context; map displayed field errors/status from server responses. `_group.css` supplies the shared visual system. |
| `_shared/demoSession.ts`, `_shared/validation.ts` | `useDemoSessionState<T>(key, initialValue)` owns tab-session draft/acknowledgement state; `Assumptions`/`InputKey` type scalar values. | Session keys are project-scoped in this prototype. Validation is client-only and resettable; it is not a domain authority. | Do not migrate the session hook as persistence. Verify canonical schema, server-side validation, authorization and conflict behavior. |

### Workbook navigation and editable inputs

| Source | Props and state owner | Current data and interaction | Harvest / integration boundary |
|---|---|---|---|
| `ModelWorkspace.tsx` | No props. Owns scalar/cost-line drafts and saved checkpoints through `useDemoSessionState`; owns active sheet/section, edit/pending guards, frequency and displayed PPA/facility context. Child modules report dirty state through callbacks. | Coordinates navigation, client validation, local Save acknowledgements, and a Run action that opens the fixed Results reference only. | It is a prototype composition root, not a production state container. Server must own Working Copy revision, Save/CAS, Run authorization and output freshness. See BROWSER cases Input Grid, Save/Run and Back/Forward. |
| `_workbook/WorkbookNavigation.tsx`, `catalog.ts` | Navigation receives `{ active: string; onSelect?: (id: string) => void }`; catalog entries carry a `SurfaceState` (`Interactive demo`, `Visual mock`, `Unavailable`) and destination metadata. | Selects sheets or navigates to explicit demo/gated surfaces. Some destinations are intentionally unavailable, not dead feature implementations. | Map to verified server routes and server-owned capability flags. URL sheet IDs are navigation context only. Uses `workbook.css`. |
| `_workbook/ModuleSurface.tsx` | Receives `{ sheet, onOpen, errors, onDraftDirty, onContextChange }`; composes module workspaces and relays dirty/context changes to `ModelWorkspace`. | Routes the selected sheet to form, grid, finance, scenario, credit, delivery or gated content. | Keep one owner for each mounted subtree; never let a future HTMX swap replace a live React-owned island without an explicit teardown/remount contract. Uses `workflows.css` and shared workbook styles. |
| `_workbook/InputGrid.tsx`, `_workbook/gridPaste.ts` | Input grid props: `values`, `committed`, `errors`, `onChange`, `onSave`, `onRun`, `onEditing`, `blocked`, `dirty`, optional `runBlocked`. Owns active cell/edit buffer/undo stack. | 21 scalar examples plus locked display/reference cells. Keyboard contract: Enter/F2 edit, Enter/Shift+Enter stage/move, Tab/Shift+Tab, Escape cancel, arrows select, Ctrl/Cmd+Z undo. Scalar TSV paste validates the full batch before staging. BROWSER case Input Grid. | Map stable field IDs, units, allowed editability and revision to canonical server validation. Scalar Save is a whole demo batch; it is not a request contract. Formula/value bar is display-only. Uses `workbook.css`. |
| `_workbook/CostLinePlanner.tsx`, `_workbook/periodGrid.ts` | Planner props: `sheet`, `values`, `committed`, `operationPeriod`, `onOperationPeriodChange`, `onChange`, `onSave`, optional `onEditing`/`onPendingError`. Parent owns draft values; planner owns selection/range/edit buffer, view, profile, precision, collapse, errors and undo. | CAPEX 18 monthly periods; OPEX 12 editable quarters and six separately authored locked half-year references, plus a longer UX fixture. Keyboard navigation, cell edit/cancel, range selection and atomic rectangular TSV validation. CAPEX/OPEX line Save is separate from Run. BROWSER case Period grids. | Verify canonical cost-line IDs, project calendar, permitted periods/units, batch atomicity and row-writer semantics. Profile selectors change explanatory copy only; no spend, escalation, aggregation or totals are generated. `period-grid.css`; data/validation helpers in `periodGrid.ts`. |

### Revenue, capital structure and analysis

| Source | Props and state owner | Current data and interaction | Harvest / integration boundary |
|---|---|---|---|
| `_workbook/RevenueWorkspace.tsx` | Receives `onDraftDirty(id, dirty)` and `onSelectContract(id)`; owns a typed PPA-A/B/C draft map, saved map, active contract and notice in tab session/local React state. | Fixed, Indexed and Scheduled sample contracts; editable dates, tariff, allocation, index terms and scheduled markers, with local validation/acknowledgement. BROWSER case PPA and facilities. | Need canonical contract identity, calendar, allocation, overlap, merchant residual, source evidence and validation rules. No allocation, shaping, P50/P90 or settlement calculation is implemented. |
| `_workbook/FinanceWorkspace.tsx` | Receives `{ sheet, onOpen, onDraftDirty, onSelectFacility }`; owns five independently selectable facility/equity draft and saved records plus the active facility. | Senior A/B, Junior/Mezzanine, SHL and Sponsor Equity fields; validation and local Save. Sources & Uses/reserves are fixed static snapshots. | Map only editable inputs to verified facility/source records. Read-only S&U, debt schedule and credit links are navigation, not reconciliation or sizing. `workflows.css`; acceptance case Financing. |
| `_workbook/TimelineTaxWorkspace.tsx` | Receives `onDraftDirty`; owns separate timeline and tax draft/saved state and a local view selector. | Basic date sequence/rate/depreciation/tax labels and local validation/acknowledgement. | Canonical jurisdiction, depreciation, tax basis, timing and cash-flow semantics must be verified. No tax/depreciation/VAT calculation exists. |
| `_workbook/ScenarioGovernanceWorkspace.tsx` | Receives `{ sheet, onDraftDirty }`; owns local scenario draft/saved maps, selected scenario and notices. | Local assumption examples; history/diagnostics are fixed illustrative surfaces. | Need stable scenario IDs and authorized persistence/run snapshots. No scenario execution, run ledger or integrity certification. |
| `_workbook/DecisionAnalysisWorkspace.tsx` | Receives `sheet`; owns selected run IDs, sensitivity driver/outcome and Goal Seek target/display values. | Fixed authored compare/sensitivity examples; Goal Seek is setup-only/unavailable. | Solver, period alignment, comparison snapshots and calculation authority are absent; do not attach the UI to guessed APIs. |
| `_workbook/CreditDecisionWorkspace.tsx` | No props; owns facility, lender-case and annual/model-period display selection. | Fixed period-level lender examples; all statuses remain observed/review/unavailable/not evaluated. | Requires verified lender policy, run evidence, covenant definitions and approval permissions. No covenant pass or decision is calculated. |

### Results, delivery, gates and styles

| Source | Props and state owner | Current data and interaction | Harvest / integration boundary |
|---|---|---|---|
| `_workbook/StatementWorkbook.tsx` | Optional `{ onSheetChange(id) }`; owns statement, annual/model-period, debt facility, initial-period visibility, expanded groups, trace selection, unit/precision and scroll restoration. | Six fixed synthetic sheets; tab switching, expand/collapse, display controls, cell focus and navigational trace/return. BROWSER case Statements. | A future surface must be a read-only projection of an identified persisted Run and revision. The current trace is not formula lineage; no statement values are computed or reconciled. `statements.css` and `workbook.css`. |
| `ResultsAnalysis.tsx` | No props; owns selected statement/section, history/scenario panel, KPI trace and selected illustrative scenario. | Fixed IRR/NPV/DSCR and statement fixtures; opens Run History and Scenario Comparison, then links to workbook context. | All displayed results remain synthetic and input-independent. Preserve the `UNKNOWN`/`NOT EVALUATED` semantics until persisted evidence exists. Uses `ResultsAnalysis.css`, `_group.css`, `workbook.css` and `statements.css`. |
| `_workbook/ModelDeliveryWorkspace.tsx` | Receives `sheet`; no data persistence or file owner exists. | Trust, Excel migration and export layouts are disabled/preview-only designs. | File parsing, export generation, storage, security, provenance and permissions are not implemented. |
| `_workbook/ModuleSurface.tsx`, `catalog.ts` gated entries | Gated entries are rendered from the catalog and selected by sheet identity. | BESS/storage, developer, acquisition, investor waterfall and other technology families are visibly unavailable/preview-only. | Product release authority must be checked server-side. A client-visible catalog entry is not a released or authorized feature. |
| `_group.css`, `ResultsAnalysis.css`, `_workbook/workbook.css`, `workflows.css`, `period-grid.css`, `statements.css` | Styles only; state remains in the React components above. | Shared light/navy FINCO visual language, responsive layout, table scroll/sticky/focus treatments and reduced-motion behavior. | These are prototype CSS assets, not a production design-token package. Scope styles to a single React island or deliberately port the needed tokens; verify no HTMX/legacy page style collisions. |

## Integration boundaries to preserve during harvest

- **Read/write authority:** all React inputs are demo-only until an approved server contract is verified. Server-side identity, permissions, feature flags, validation and persistence must remain authoritative.
- **Save shapes:** scalar Input Grid presents one atomic batch; CAPEX/OPEX use distinct line-batch saves; Revenue, finance, tax and scenario forms acknowledge separate local records. Whether canonical FINCO supports these transaction boundaries is **NEEDS_GITHUB_VERIFICATION**.
- **Run and output:** the prototype Run button opens fixed `DEMO-FIXED-018`; it does not invoke a model. A future integration must keep Save distinct from Run and obtain persisted Run/revision evidence before showing `CURRENT`.
- **Navigation:** query/hash state preserves selected sheet, project, contract/facility/scenario and trace display context only. It is not authentication, persistence, a stable server ID contract or proof of calculation lineage.
- **React/HTMX ownership:** the prototype has no HTMX lifecycle integration. For a React island, assign one owner per DOM subtree and verify mount/unmount, listeners, focus/scroll restoration, and out-of-band swap behavior before release.
- **Verification evidence:** manual PASS cases and remaining untested scope are in `BROWSER_ACCEPTANCE.md`; release states and top ten design gaps are in `COVERAGE.md`. No production implementation or public API was inspected.

## Copy-ready GitHub Architecture PoC assignment (documentation only)

The following prompt is prepared for a later, separately authorized task. It is not being submitted to GitHub now:

> Inspect the current authorized FINCO repository and its exact HEAD before editing. First identify the existing server-rendered workbook shell, project access/auth/CSRF pattern, canonical editable field registry, validation and Save/CAS boundaries, persisted Last Run/RuntimeResult projection, feature-flag convention, CI commands and staging procedure. Cite actual paths and tests; do not infer or invent an endpoint, schema, class or release gate.
>
> If—and only if—the real canonical contracts support it, implement one narrow Architecture PoC behind an OFF-by-default release flag: (1) one existing scalar project input saved through the canonical server-side validation and compare-and-swap/revision mechanism, rejecting stale/unauthorized/invalid edits atomically and showing an explicit conflict; and (2) one existing read-only persisted statement view sourced from a real Last Run, showing its Run ID/version and truthful `CURRENT`, `STALE` or `UNKNOWN` state based on matching committed revision evidence. Do not add or invoke a Run, change financial calculations, create new endpoints without owner approval, or replace the current page. Preserve the existing route as fallback.
>
> If React islands are chosen, prove one DOM owner per island and test HTMX mount/unmount plus any OOB swap that can cross the boundary; preserve same-origin auth/CSRF, keyboard/focus/scroll behavior and accessible validation. Measure bundle/performance impact. Add exact-HEAD CI, permission, CAS conflict, stale/current, no-auto-Run and fallback tests. Request an independent read-only review; do not merge or deploy. Use the normal review/merge path only after owner approval, and perform staging acceptance only with explicit authorization. If any required canonical contract is missing, stop and report the evidence instead of building a mock adapter.
