# UX-03 — RC11 Presentation Completion + Three-Theme Layer (B/D/G)

**Status:** Draft PR, feature flag `FINCO_MODEL_REACT_V1` stays OFF. No merge, activation or deployment is performed or authorized by this document.

## 1. Provenance

| Source | SHA-256 |
| --- | --- |
| RC11 clean intake ZIP (`FINCO_RC11_GLM_GITHUB_INTAKE_CLEAN.zip`) | `8f4af7de91f3140f69af91c0a0c8de225dbeef15aa320e0c58fcb8046ce4efb0` |
| Original standalone RC11 (reference, 183 members) | `4d207ed0f0270dee94a0059077aae36b2e0aa4e214c2a99da6e550b914b541da` |
| Theme Lab B/D/G handoff ZIP (`finco-theme-lab-bdg-glm-handoff.zip`) | `8fab8327256043eb437feb18d95928283b4d9b58280c8512f259bf2c53fccb19` |

All 97 RC11 manifest entries and all 18 Theme Lab manifest entries validated byte-for-byte (0 missing, 0 mismatches). Theme Lab source HEAD `522b4ef0a7777a3ccc340aa2e795131cf791d46e`; its final LIGHT G palette is used (obsolete dark-G `#164B3A` shell is not).

## 2. Component inventory (RC11 → `frontend/src/finco/`)

**Ported with reconciliation (canonical UX-02 semantics preserved):**
- `_workbook/StatementWorkbook.tsx` — RC11 refresh + the documented single source adaptation (`regionRef: React.RefObject<HTMLDivElement>`; RC11's React-19 `| null` typing rejected) + Epic's canonical `integrity` union kept.
- `ResultsAnalysisView.tsx` — RC11 Insight/explain/plain-status presentation over Epic's canonical truth elements: `ResultsOriginNotice`, `runStateLabel` (incl. `CURRENT · persisted Last Run`), `freshnessLabel`, `DemoContextStrip`, the `fm-result-lineage` working-copy/last-run section and the `fm-wb-status` independent status dimensions are Epic's originals.
- `ResultsAnalysis.tsx` (demo composition, not production-reachable), `_shared/SourceAuthorityDrawer.tsx`, `_workbook/{CostLinePlanner,CreditDecisionWorkspace,DecisionAnalysisWorkspace,FinanceWorkspace,RevenueWorkspace,ScenarioGovernanceWorkspace,TimelineTaxWorkspace,ModelDeliveryWorkspace,ModuleSurface,InputGrid,WorkbookNavigation,catalog}.tsx/.ts`.
- New presentation: `_insight/{insightContract,FincoInsightPanel,FindingsWorkspace,insight.css}`, `_workbook/{OverviewWorkspace,overview.css}`, `_shared/{plainLanguageStatus,draftNavigation}`, `_workbook/FINCO_I26_QA_REPORT.md`.
- `_group.css` — RC11 additions WITHOUT the Google Fonts `@import` (remote font fetch stays eliminated; local fallbacks unchanged).
- Quarantined demo infra refresh: `_shared/{demoSession,demoSessionKeys,demoWorkingCopies}` + new `_shared/demoSessionStorage(.test).mjs`.

**Kept Epic/canonical (RC11 versions rejected as demo-wired):**
- `_shared/FincoShell.tsx` (RC11 imports demoSession/sessionStorage/"Adriatic Solar I"), `ProjectLibrary.tsx` (RC11 imports `SYNTHETIC_REFERENCE_PROJECTS`), `_shared/viewModels.ts`, `_results/resultsContract.ts` (Epic's `runState` keeps `"current"`; RC11 dropped it), canonical `integrity` union in `statementContract.ts` (Epic's `"not evaluated" | "UNAVAILABLE" | "PASS" | "FAIL" | "INCOMPLETE"`; RC11's weakened `"not evaluated"` rejected). `motion/validation/gridPaste/periodGrid/statements.css/workbook.css/workflows.css/ResultsAnalysis.css/period-grid.css` are content-identical to RC11 after newline normalisation (EOL-only).
- Reconciled contracts so the canonical UX-02 callers keep compiling: `ModuleSurface.onScenarioChangeRequest` optional (absent = proceed directly, as before), `CostLinePlanner.onSave: () => boolean | void` (only literal `false` is a refused save).
- `statementContract.ts` gained the additive `onExplain?: (item: InsightExplainInput) => void` hook (presentation-only; the caller owns all displayed values).

**Quarantined (never production-imported):** `syntheticInsightFixtures.ts`, all `demo*`/`synthetic*`/`runComparisonFixtures` modules, `frontend/transfer/**`. `FORBIDDEN_PRODUCTION_MODULES` extended with `_shared/demoSessionStorage.ts` and `_insight/syntheticInsightFixtures.ts`; the harvest module-graph regex extended accordingly (guard strengthening, no guard weakened). Served bundle `static/react/finco-react.js` verified free of every forbidden marker including `sessionStorage`.

## 3. Three-theme layer (UX-03B)

- IDs: `b-slate-teal`, `d-high-contrast`, `g-forest-green-white` (labels "Slate & Teal", "High-Contrast", "Forest Green / White Workbook"). Absence of a selection = shipped default look.
- Implementation: `finco/_shared/theme.ts` (pure storage/apply logic, never throws, unknown values fall back), `finco/_shared/ThemeSelector.tsx` (`ThemeProvider` + native `<select>`, `aria-label`, keyboard operable), selector placed in the React shell top bar. Attribute `data-fm-theme` is set **only on the React mount root**, never on `documentElement` — the legacy Jinja/HTMX UI cannot be restyled.
- Tokens: `styles/fm-themes.css` overrides the `--fo-*` design tokens (rx-* surface) and the `.finco-root` fm tokens per theme; G adds chrome tokens (top bar `#317B5D`, shell rail `#2E765B`, active-nav text `#174A36` on mint `#E5F3EB`, control line `#6B8072`, soft lines `#D4E1D9`/`#E7EEE9`, accent/focus `#246347`) over a white content canvas; grid/editable cells stay white; state colours (positive/caution/danger/info) follow the Theme Lab values. State semantics (CURRENT/STALE/FAILED/NOT RUN/UNKNOWN/NOT EVALUATED/UNAVAILABLE and editable/calculated/read-only/locked/unavailable) keep their text labels and badges — colour is never the sole carrier. Storage key `fincoReactTheme`, persisted with `localStorage` and a deterministic no-theme fallback when storage is unavailable.
- Responsive: the top bar wraps below 760 px instead of overflowing; no element (incl. the data-origin label) is hidden. Fixed the 390 px horizontal overflow regression the browser acceptance caught during local testing.
- No runtime dependency added; `dependencies` remain `react`/`react-dom` 18.3.1 (guard `test_production_dependency_surface_unchanged` keeps enforcing this).

## 4. Gated surfaces — truthful non-connections

These RC11 surfaces render **only** as design-library or explicitly gated presentation; none is presented as backend-functional:

| Surface | State | Missing canonical contract (owner of the gap) |
| --- | --- | --- |
| Insight findings (review) | Panel renders over caller-supplied findings only; production callers pass none → honest "could-not-check/unknown" states | No backend insight/findings endpoint (Model owner; requires a canonical read authority before any wiring) |
| Insight explain | Dialog explains values already presented from canonical snapshots; supplies no data | Presentation-only by design; no backend needed |
| Scenario selection/comparison, sensitivity, goal-seek | Design-library + gated nav section (D4) as in UX-02 | Scenario persistence/authoring authority (Model owner) |
| Run History panel | Renders caller-supplied persisted records only; empty list stays empty | Already canonical via persisted Run evidence in UX-02; RC11 additions are presentation-only |
| Overview / model-delivery / timeline-tax / catalog extensions | Design library (reachable via hash routing in the demo composition, not production) | Router admission decision separate from this PR |
| Merchant revenue, workbook import, exports | "Unavailable" states carried through verbatim | Not designed in RC11 by intent |

## 5. Local acceptance (Windows, Python 3.12, Node 24)

- `tsc --noEmit` + `tsc -p tsconfig.finco.json --noEmit`: clean. `vite build` + transfer build: clean; bundle published to `static/react/`.
- `node --experimental-strip-types --test`: `theme` 5/5, `insightContract` 5/5, `plainLanguageStatus` 3/3, `periodGrid` 9/9, `demoSessionStorage`+`demoWorkingCopies` 14/14 — all pass (new tests use the GitHub tree paths; the pre-existing `resultsContract/statementContract/transferRoutes/demoAdapter` .mjs tests still reference the historical Replit layout and are not wired to any workflow — unchanged by this PR).
- pytest: `test_model_react_ux02_workspace_v1.py` + `test_model_react_source_harvest_v1.py` + `test_model_react_source_rc5_v1.py` + `test_model_react_poc_browser_acceptance.py` + `test_ci_acceptance.py` — **136 passed, 0 failed** (includes the exact-head ancestry guard, source-quarantine/bundle guards, canonical Save/CAS/409/UNKNOWN flows and the Chromium acceptance pass at 1440/900/390/320 after the responsive fix).
- Historical `test_package_checksums_recorded` provenance (RC5/RC6/RC7 SHAs) untouched.

## 6. Boundary declaration

No `financial_engine/`, `finco_core/` or `domain/` file is authored or modified by this branch's UX-03 commits; the branch carries one normal two-parent merge of `origin/main` (`b6bbb144`) solely to satisfy `test_frozen_financial_namespaces_unmodified`'s live `origin/main`-ancestry requirement (same precedented pattern as merged PR #343). No rebase/squash/force-push; no merge, deployment or activation.
