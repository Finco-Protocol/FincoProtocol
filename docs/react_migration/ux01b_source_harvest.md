# UX-01B — Replit React source harvest & integration plan

Branch: `feat/ux01b-react-source-harvest-v1` (stacked on `feat/ux01-full-react-poc-v1`,
which is stacked on `epic/model-react-frontend-v1`). Draft PR target: the epic
branch — never `main`.

## 1. Source package intake (verified)

| Item | Value |
|---|---|
| Package | `finco-react-transfer-rc1.zip` (owner-supplied, Replit "GoldenNiceConsultant" project) |
| SHA-256 | `3b205723dea75383238036e99a7f65a6ee7f7826b15c0ea9a5794356893e159d` |
| Integrity | `unzip -t` clean; **69 actual file members** (`unzip -Z1`: 69 entries, none of them directory entries); no `node_modules`, no compiled bundles, no screenshots, no git metadata, no secrets. The often-quoted "70 members" is an artifact of `unzip -l` column output: one long filename (the 123 KB browser-smoke script) wraps onto a second line, inflating the data-line count by one. 37 of the 69 files are code under `src/components/mockups/finco-model/`, harvested 1:1 into `frontend/src/finco/` |
| Origin revision | workspace `26ade41` (`main`), per the package's own completion report |
| Docs preserved verbatim | `docs/react_migration/replit_source/` (report, harvest manifest, integration readiness, component handoff, coverage, browser acceptance, transfer progress + the `_workbook` sub-docs) |
| Runtime dependencies of the FINCO subtree | **`react` only** (18× imports); every hook used is React-18 compatible (`useState/useEffect/useMemo/useRef/useCallback/useId`) |
| Sandbox-only dependencies NOT harvested | Tailwind v4 entry (`src/index.css` = gallery/shadcn scaffolding — the FINCO `fm-*` tokens are self-contained in `_group.css`), Radix/recharts/framer-motion catalogue entries, `@replit/*` plugins |
| TypeScript | Compiles under React 18.3 types after ONE documented adaptation (below); sandbox used React 19.1 types |

## 2. What was transferred where

| Package path | Repo path | Nature |
|---|---|---|
| `src/components/mockups/finco-model/**` (tsx/css) | `frontend/src/finco/**` | Design source tree, as supplied (37 files incl. README) |
| `src/finco-transfer/**`, `index.transfer.html`, `vite.transfer.config.ts` | `frontend/transfer/**` | Dev-only preview harness (own Vite config, never served by FastAPI, not in CI) |
| `scripts/*.mjs` (unit + browser smoke) | `frontend/transfer/scripts/` | Design-QA infrastructure (sandbox-scoped; not wired into repo CI) |
| Package root + `_workbook` `*.md` | `docs/react_migration/replit_source/` | Verbatim handoff record |
| `src/index.css`, sandbox `package.json` catalogue | **not transferred** | Tailwind/shadcn gallery scaffolding + catalogue versions — target-app responsibility (documented) |

Adaptations (complete list, kept minimal):
1. Harness import paths re-pointed to the harvested layout (`../src/finco/...`).
2. Harness imports `_group.css` (FINCO tokens) instead of the Tailwind gallery entry.
3. `transfer/vite.config`: Tailwind plugin + `@` alias dropped (unused by the subtree).
4. **One source-line adaptation:** `StatementWorkbook.tsx` prop `regionRef` widened from the
   React-19-style `RefObject<HTMLDivElement | null>` to the React-18-compatible
   `RefObject<HTMLDivElement>` (call site already passes exactly that). Pinned by test.
5. `@types/node` added as a devDependency (transfer config uses `import.meta.dirname`);
   **runtime dependencies unchanged** (react + react-dom only — pinned by test).

## 3. Component reuse matrix

Classes: **DIRECT** = directly reusable · **ADAPT** = reusable with adaptations ·
**REFACTOR** = requires refactoring before product use · **REBUILD** = behaviour must be
rebuilt on canonical authority (visual/layout may transfer).

| Replit source | Target React module | Dependencies | Required adapter | Status |
|---|---|---|---|---|
| `_shared/FincoShell.tsx`, `FincoApplicationComposition.tsx` | `frontend/src/finco/_shared/*` | `_group.css`, navigation bridge | Route adapter (replace URL/sessionStorage bridge with the app router) | ADAPT |
| `ProjectLibrary.tsx` | `frontend/src/finco/ProjectLibrary.tsx` | `_group.css`, demo fixtures/session | `ProjectLibraryProps` fixture injection → typed Library read model (`resolve_accessible_project`-backed); protected-Reference copy flow → canonical working-copy creation | ADAPT |
| `ModelWorkspace.tsx` (35 KB shell) | `frontend/src/finco/ModelWorkspace.tsx` | `_workbook/*`, `_shared/demoSession`, `demoWorkingCopies` | Decouple demo session/URL state → typed workbook context (composite CAS identity, scenario); nav via route adapter | REFACTOR |
| `_workbook/InputGrid.tsx` + `gridPaste.ts` | kept | `workbook.css` | `InputGridProps` (controlled values/committed/callbacks) → canonical field registry + `POST /v2/workbook/grid/save` (scalar C0 writer, composite CAS, CSRF) | ADAPT (presentation DIRECT) |
| `_workbook/CostLinePlanner.tsx` + `periodGrid.ts` | kept | `period-grid.css`, `workflows.css` | `CostLinePlannerProps` → the EXISTING `POST /v2/workbook/grid/cost-lines/save` atomic cost-line writer (row versions) — never the scalar writer | ADAPT (presentation DIRECT) |
| `_workbook/RevenueWorkspace.tsx` | kept | `workflows.css` | PPA drafts → canonical revenue registry fields + revenue contract routes | REFACTOR |
| `_workbook/FinanceWorkspace.tsx` | kept | `workflows.css` | Facility drafts → financing editors authority (F1–F3); no client sizing | REFACTOR |
| `_workbook/StatementWorkbook.tsx` + `statementContract.ts` + `statements.css` | kept | — | `StatementWorkbookProps` (`snapshot`, `status`, `onSheetChange`) → bootstrap-style authorized projection over `PostRunRequestContext` + statement services (the UX-01 P&L projection generalised) | ADAPT (presentation DIRECT) |
| `ResultsAnalysis.tsx` | kept | `ResultsAnalysis.css` | Accepts external typed statement/status fixture → persisted RuntimeResult projection; charts stay presentational (no client calculation) | ADAPT |
| `_workbook/TimelineTaxWorkspace.tsx` | kept | `workflows.css` | Tax sheet → `tax.*` registry fields (incl. `tax.assumptions.cit_rate_pct`, proven in UX-01) | ADAPT |
| `_workbook/ScenarioGovernanceWorkspace.tsx` | kept | `workflows.css` | Scenario drafts → scenario authority + override authority | REFACTOR |
| `_workbook/CreditDecisionWorkspace.tsx`, `DecisionAnalysisWorkspace.tsx`, `ModelDeliveryWorkspace.tsx`, `ModuleSurface.tsx` | kept | `workflows.css` | Synthetic review/gate UI → credit/decision/diagnostics/trust read models; feature gates server-owned | REBUILD (behaviour) / VISUAL |
| `_workbook/catalog.ts` | kept | — | Route/module catalogue → app route table (it is navigation data, not server contract) | ADAPT |
| `_shared/viewModels.ts`, `validation.ts` | kept | — | UI view-model types → keep as presentation layer over canonical DTOs; validation display only (server validates) | DIRECT/ADAPT |
| `_shared/demo*` (adapter, session, working copies, fixtures) | kept under `src/finco/_shared/` | — | **DELETE/replace per domain** — never wire into production; quarantined by test | QUARANTINE |
| `frontend/transfer/**` (harness + smoke scripts) | dev-only | — | None — design review harness; not served, not in CI | DEV-ONLY |

## 4. UX-01 progress & overlap resolution

UX-01 (PR #338, this stack's base) already implements: flag-gated shell, canonical
CIT input Save (CAS/CSRF), persisted P&L, STALE/CURRENT/NOT_RUN + integrity badges.
No harvested component replaces that working code in THIS PR. Overlap resolution:

- `frontend/src/finco/**` is quarantined source (production bundle unchanged — test-pinned).
- The first domain swap (recommended: **Statements → `StatementWorkbook`**, since its typed
  props boundary maps 1:1 onto the UX-01 bootstrap projection) happens in a scoped
  follow-up PR, replacing the temporary PoC views behind the same data contract.
- UX-00 manifest, parity matrix and canonical-contract docs remain authoritative.

## 5. Dependency & build reconciliation

- React 18.3.1 + Vite 5.4 (target app) compile the full harvested tree (`tsc -p tsconfig.finco.json`
  clean; `npm run build:transfer` produces working lazy chunks for Library/Workspace/Results).
- No new runtime dependency; `@types/node` added as dev-only.
- The sandbox catalogue's exact versions (React 19.1 / Vite 7.3.6 / Tailwind 4.3.3) are NOT
  required by the FINCO subtree; adopting them is a separate, owner-gated decision.

## 6. PR sequencing

1. **#338 (UX-01)** — foundation; review/merge first.
2. **UX-01B (this branch)** — source transfer + quarantine + integration plan.
3. **UX-01B.1 (proposed)** — Statements domain: `StatementWorkbook` onto the bootstrap
   projection; replace PoC P&L views; parity tests extended.
4. **UX-01B.2 (proposed)** — Inputs domain: `InputGrid` onto the canonical grid save
   (CIT + p50/tariff), conflict/typed-preservation UX from the PoC reused.
5. **UX-01B.3 (proposed)** — Library/shell swap with route adapter + legacy link parity.
6. Run button only after the thin read-only Run-outcome adapter is agreed (deferred in UX-01).

## 7. Missing files / build blockers

- None blocking. Recorded for the next stage:
  - The Replit sandbox's `tsconfig.base.json` and gallery preview plugin were not part of the
    ZIP (not needed — harvested tree compiles under the target's configs).
  - Full axe/WCAG, screen-reader, OS-clipboard and cross-browser validation of the design
    source remain open per the package's own report (design QA scope, not repo CI).
  - Design-source Chromium smoke suite (`frontend/transfer/scripts/finco-browser-smoke.mjs`)
    is sandbox-parameterised; wiring it to this repo's harness is optional follow-up, not CI.
