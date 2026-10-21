# FINCO Iteration 20 — statement provider separation report

Date: 2026-10-21  
Scope: the isolated GoldenNiceConsultant FINCO Design sandbox only. No GitHub, backend, engine, database, deployment, or production data was used.

## Result

**W1–W6: PASS for the requested design/source boundary.** The statement table is now presentation-only with typed caller-supplied data. The existing Canvas page still supplies its fixed synthetic snapshot through its demo wrapper; the standalone transfer route supplies its separate transfer fixture. An explicit unavailable snapshot does not silently fall back to sample statement rows.

This does not establish production API/DTO compatibility, persistent Last Run provenance, calculation correctness, reconciliation, or financial parity. Production field IDs and server contracts remain `NEEDS_GITHUB_VERIFICATION`.

## Workstream evidence

| Workstream | Status | Evidence |
| --- | --- | --- |
| W1 source inventory | **PASS** | Inspected `StatementWorkbook.tsx`, `statementContract.ts`, `ResultsAnalysis.tsx`, the new `ResultsAnalysisView.tsx`, `src/finco-transfer/fixtures.ts` and `src/finco-transfer/App.tsx`. The workbook exposes six sheets: P&L, Balance Sheet, Cash Flow, CFADS, Debt Schedule and Sponsor Returns; eight annual periods, eight selected model snapshots with three period bands, and separate Senior/Mezzanine statement rows. |
| W2 fixture separation | **PASS** | All six statement trees, periods, bands, facility rows and demo status moved to `_workbook/syntheticStatementProvider.ts`. A structural comparison against pre-change `HEAD` confirmed the values, nested row order and IDs were unchanged. `StatementWorkbook` reads only its required typed `snapshot` and `status` props; chart/KPI fixtures remain independent and are not reconciled. |
| W3 reusable boundary | **PASS** | `ResultsAnalysisView.tsx` accepts caller-owned `StatementWorkbookSnapshot | null` and `StatementRunStatus`. The existing Canvas component path `ResultsAnalysis.tsx` is a thin synthetic-demo wrapper. Transfer imports `ResultsAnalysisView` directly and supplies its separate fixture. The transfer bundle contains neither the Canvas-only provider marker nor the Canvas-only `balance-check` row ID. |
| W4 test contracts | **PASS** | `test:statement-contract` is 7/7: six stable sheet identities and row order, annual/model widths and bands, separate facility rows, fixed status, negative/zero/unavailable semantics, caller replacement, explicit `null`, and no fixture import in the presentation graph. |
| W5 browser/keyboard/visual | **PASS for tested Chromium scope** | Fresh full suite: 22 PASS / 0 FAIL / 2 UNTESTED of 24. It exercised the three existing preview routes, six sheet tabs, annual/model switch, Senior/Mezzanine rows and trace return; the local transfer build's direct route/reload/history, null-snapshot unavailable view and responsive 1440/900/390/320 layouts; Copy A/B and working-copy journeys; 60/80/120Q layouts; keyboard and internal scrolling. No browser runtime errors were captured. |
| W6 acceptance | **PASS** | Fresh TypeScript typecheck, Design Vite build, transfer Vite build and 39/39 unit tests passed. The final RC4 archive also passed clean extraction, frozen install, typecheck, transfer build and 39/39 unit tests under Node 24.13.0 / pnpm 10.26.1. The first extraction test exposed an older `FincoShell` prop type carried in RC3; RC4 includes the current unchanged shell source and the clean build then passed. The transfer build was served on a temporary local Vite Preview server at `127.0.0.1:4173`, not published or deployed. |

The two browser cases left **UNTESTED** are the axe accessibility engine and Firefox/WebKit, because those tools/engines are not installed in this sandbox. Host OS clipboard and screen-reader/full WCAG testing also remain untested. Browser clipboard-event coverage is not OS clipboard coverage.

## Exact source and documentation changes

- `src/components/mockups/finco-model/_workbook/syntheticStatementProvider.ts` — new Canvas-only fixture module.
- `src/components/mockups/finco-model/_workbook/StatementWorkbook.tsx` — removed embedded row/period/facility fixtures; requires typed snapshot/status; explicit unavailable and no-rows states.
- `src/components/mockups/finco-model/_workbook/statementContract.ts` — added `resolveStatementSnapshot`, preserving the difference between omitted demo props and explicit `null`.
- `src/components/mockups/finco-model/ResultsAnalysis.tsx` — retained Canvas component path as a demo-only wrapper.
- `src/components/mockups/finco-model/ResultsAnalysisView.tsx` — new shared typed page view; no Canvas fixture import.
- `src/components/mockups/finco-model/_shared/FincoShell.tsx` — unchanged workspace shell included in RC4 from current source so its `mainContentId` prop contract matches the results view; the prior RC3 snapshot had an older shell type and failed a clean extracted typecheck.
- `src/finco-transfer/App.tsx` and `src/finco-transfer/context.tsx` — transfer uses the view directly and supports an explicit QA-only `qaStatement=empty` state.
- `src/.generated/mockup-components.ts` — the preview component catalog now lists `ResultsAnalysisView`; Canvas state still has only the three original FINCO frames (`finco-library`, `finco-workspace`, `finco-results`). No new Canvas shape was created.
- `scripts/statementContract.test.mjs` — provider and import-boundary tests.
- `scripts/finco-browser-smoke.mjs` — served-build null snapshot assertion, transfer fixture isolation assertion, and wait conditions that confirm the restored cell value rather than only route navigation.
- `BROWSER_ACCEPTANCE.md`, `COVERAGE.md`, `UI_COMPONENT_HANDOFF.md`, `INTEGRATION_READINESS.md` — additive Iteration 20 evidence and boundary notes.

The browser run wrote `test-evidence/iteration-20-final-browser-results.json`. Existing smoke-script screenshot outputs with `i16-*`/`i18-*` filenames were refreshed during this run; their current contents are Iteration 20 captures. No test screenshot was deleted.

## Remaining limits

- No axe scan, screen reader, full WCAG audit, Firefox/WebKit, iOS Safari, or host-OS clipboard test.
- Annual and model-period statement values remain fixed illustrative strings; KPI/chart arrays are separate and intentionally not reconciled with them.
- No actual finance formulas, Run, persistence, API adapter, auth, authorization, CAS, or backend DTOs.
- `ResultsAnalysis.tsx` is demo-only; future application code should import `ResultsAnalysisView` and inject verified server-owned data/status.
- RC1/RC2/RC3 archives were preserved; RC4 packaging is separate and source-only.
