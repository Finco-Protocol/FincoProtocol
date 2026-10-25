# UX-02 — Replit source reconciliation & integration record (RC5 → RC6 → RC7)

Status: implemented on `feat/model-react-ux02-core-integration-v1` (based on the React epic branch).
The RC1 record (`replit_source/` + `tests/test_model_react_source_harvest_v1.py`) remains the
historical authority for the RC1 era; this document supersedes it for the current tree.

## 1. Package verification

| Package | SHA-256 (verified live at intake) | Members | Integrity | Disposition |
|---|---|---|---|---|
| RC5 `finco-react-transfer-rc5.zip` | `74b792e0a0411e779dbc0085e8a4c560893866ea2cc68a29ff57e6f8d92352e2` (matches the owner's expected value) | 89 | `unzip -t` clean | base snapshot, overlaid |
| RC6 `finco-react-transfer-rc6.zip` | `7f75f389d87eb55e8253b05032437a7f878b1dbf380f0dafb82a5475bcbf7957` (matches the owner's expected value) | 17 | clean | delta, overlaid second |
| RC7 `finco-react-transfer-rc7.zip` | `5f531c8060882da1fd6ee35c6f3621b945214c5c999c40cc261279c1fba1d0fc` (owner-accepted delta; byte-identical to the first-supplied copy) | 13 | clean | overlay, applied third per its own manifest |

Reconstitution order: **RC5 → RC6 → RC7** (the RC7 manifest's own order). No duplicate or
path-traversal entries in any archive (0 matches for `../` and absolute paths). No
`node_modules`, no compiled bundles, no secrets. The sandbox catalogue files (`package.json`,
`pnpm-lock.yaml`, `tsconfig.json`, `transfer-support/`, `index.transfer.html`, `src/index.css`)
were again **not transferred** — the target toolchain (React 18.3 / Vite 5 / pinned TS) owns
dependency resolution; the FINCO `fm-*` design tokens remain self-contained in `_group.css`.

## 2. Overlay result

- `src/components/mockups/finco-model/**` → `frontend/src/finco/**` (all RC5 files, then RC6,
  then RC7; 60 files touched, new: `ResultsAnalysisView.tsx`, `_results/{resultsContract,runComparisonFixtures}.ts`,
  `_workbook/syntheticStatementProvider.ts`, `_shared/{SourceAuthorityDrawer.tsx,source-authority.css}`).
- `src/finco-transfer/**` → `frontend/transfer/**` (harness path adaptations re-applied:
  `../components/mockups/finco-model/` → `../src/finco/`; `index.css` import → `_group.css`).
- Handoff docs (post-RC7) → `docs/react_migration/replit_source/rc5/` (verbatim).

### Documented adaptations (complete list)

1. Transfer-harness import paths re-pointed to the harvested layout (as in RC1).
2. Harness imports `_group.css` (FINCO tokens) instead of the Tailwind gallery entry.
3. **`StatementWorkbook.tsx` `regionRef` widened** from the React-19-style
   `RefObject<HTMLDivElement | null>` to the React-18-compatible `RefObject<HTMLDivElement>`
   (same single adaptation the RC1 era required; pinned by test).
4. **Quarantine seam `_shared/fincoProjectBridge.ts` (new):** `FincoShell.readProjectContext`,
   its demo-session reset, and `ProjectLibrary`'s local working-copy list/creation no longer
   import the demo session modules directly; they consume the neutral bridge.  The transfer
   harness installs the demo implementation (`transfer/main.tsx`); production installs none.
   `ProjectLibrary` additionally accepts `onCreateWorkingCopy` (production: the canonical
   `POST /library/clone/{id}` route) and no longer defaults to `SYNTHETIC_REFERENCE_PROJECTS`
   (callers own the project list).
5. `FincoShell.readProjectContext` demo fallback name replaced with the neutral
   "FINCO Model project" (the demo fixture name must not be shippable in production).
6. `_workbook/WorkbookNavigation.tsx` unused React import removed (React-18 JSX transform).

### Runtime dependencies

**Unchanged**: `react` + `react-dom` only (pinned by test). `@types/node` remains a dev-only
dependency. No React upgrade; the whole RC7 tree compiles under React 18.3 types.

## 3. Quarantine model (Workstream A3)

Production renders APPROVED harvested presentation components
(`StatementWorkbook`, `ResultsAnalysisView`, `FincoShell` chrome/nav, `ProjectLibrary`, their
CSS and typed contracts).  It must never include the demo/synthetic state.  Enforcement
(`tests/test_model_react_source_rc5_v1.py` + the evolved RC1 guards):

- bundle markers: demo fixtures, synthetic providers, run-comparison fixtures, product-state
  fixtures, the demo fixture project name, and `sessionStorage` itself are ABSENT from the
  served bundle;
- import graph (`tsc --listFiles`): no demo module, no synthetic provider and no transfer
  harness file appears in the production TypeScript program.

The RC1-era guard ("no harvested file in production at all") is preserved as history in
`tests/test_model_react_source_harvest_v1.py` with its scope consciously evolved — noted
here so the change is auditable, not silent.

## 4. Component reconciliation vs Workstreams B–D

| Harvested component | UX-02 disposition |
|---|---|
| `StatementWorkbook` + `statementContract` | **Connected (B)** — canonical six-destination snapshot via `GET /v2/model-react/statements` |
| `ResultsAnalysisView` + `resultsContract` | **Connected (B4)** — canonical returns/metrics projection; charts stay null (no canonical chart projection consumed yet) |
| `FincoShell` (`Shell`, `ModelNav`, `Status`) | **Connected (D2)** — production workspace chrome with `dataOrigin="caller-provided"` |
| `ProjectLibrary` | **Connected (D1)** — canonical projects/references via `GET /v2/model-react/library`; clone via canonical route |
| `InputGrid` + `gridPaste` | **Presentation patterns reused (C)** — the harvested grid's row model is a fixed synthetic assumption set, so the canonical grid (`CanonicalInputGrid`) reuses the `fm-wb` presentation and Correction-A save semantics over the canonical registry projection |
| `ModelWorkspace` | Visual-only (demo session/URL state ownership) — its shell role is filled by `FincoShell` composition |
| `CostLinePlanner`, `RevenueWorkspace`, `FinanceWorkspace`, `ScenarioGovernanceWorkspace`, `DecisionAnalysisWorkspace`, `CreditDecisionWorkspace`, `ModelDeliveryWorkspace`, `ModuleSurface`, `TimelineTaxWorkspace` | Visual-only (C6 keeps CAPEX/OPEX read-only navigation; their canonical adapters are future work) |
| `syntheticStatementProvider`, `syntheticResultsProvider`, `runComparisonFixtures`, `productStates`, `demo*` | Quarantined — never imported by production (test-pinned); available to the transfer harness only |
