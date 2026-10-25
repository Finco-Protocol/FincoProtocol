# FINCO React Design — I18 Correction A / I19 closeout

**Date:** 2026-10-21  
**Scope:** Existing isolated GoldenNiceConsultant Design sandbox only. All UI data and displayed financial outputs remain synthetic. No original FincoProtocol, GitHub, backend, database, financial engine, publish, or deployment was touched.

## Closeout

The two reported I18 browser failures were reproduced and corrected. Fresh acceptance is **22 PASS, 0 FAIL, 2 UNTESTED** across all 24 registered browser cases. The two untested cases require axe and Firefox/WebKit, which are not installed. Fresh typecheck, Design build, transfer build, and **35/35 unit tests** pass. This is Design QA evidence, not financial validation or full WCAG certification.

## W1–W7

| Workstream | Status | Evidence |
| --- | --- | --- |
| W1 — Copy A/B to Input Grid | **PASS** | The failure was a test-harness origin issue: the test accessed `sessionStorage` on `about:blank` before navigating to the app origin. The harness now opens Project Library before clearing storage. The full Chromium case verifies protected Reference, Copy A/B IDs and values, switching, session reload, and no copy-state collision. |
| W2 — Keyboard trace and return | **PASS** | Every statement value previously entered the page Tab order, so the source link could not be reached in the intended keyboard path. Statement cells now use one roving Tab stop with arrow navigation, the region describes those keys, and trace return focuses the original statement cell. Browser-tested with Tab/Enter only at desktop and 390px; the test checks focus at the source and selected-cell return. |
| W3 — Full browser acceptance | **PASS for runnable cases** | `pnpm run test:browser`: 22 passed, 0 failed, 2 untested. The entire 24-case suite ran against the existing preview and temporary localhost-served transfer build. Routes, Library, copy journey, grid, PPA/facility, six statements, trace, analysis, sticky/inner scroll, browser history, 1440/900/390/320 layouts, and console were exercised. |
| W4 — Typed presentation boundary | **PARTIAL** | Existing typed `StatementWorkbookSnapshot`/`StatementRunStatus`, `InputGridProps`, and Library prop seams remain. The correction added a typed roving-cell helper and unit test. A broad fixture/session provider extraction was intentionally deferred to avoid changing stable page ownership; statement fixtures and browser session state are still coupled to the demo shell. |
| W5 — Accessibility evidence | **PARTIAL** | Named navigation landmarks and accessible names, skip-link, keyboard-only journeys, focus recovery, visible grid instructions and reduced-motion behavior were checked in Chromium. Axe and screen-reader testing were not performed. |
| W6 — Cross-browser, clipboard and long periods | **PARTIAL** | Chromium only. Browser clipboard API TSV and all-or-nothing rejection/undo passed; host OS clipboard is untested. 320/390/900/1440 viewport tests and 60/80/120-quarter fixtures passed with sticky headers and contained horizontal scrolling. Firefox/WebKit are unavailable. |
| W7 — Evidence and source package | **PASS** | Updated evidence/docs and a source-only RC3 ZIP were prepared from RC2 as a new delta. RC1 and RC2 archives remain unchanged. RC3 identity/integrity and extracted-build result are recorded in `FINCO_REACT_TRANSFER_RC3_REPORT.md`. |

## Fresh verification

- `pnpm run typecheck` — PASS
- `PORT=5000 BASE_PATH=/ pnpm run build` — PASS
- `PORT=5000 BASE_PATH=/ pnpm run build:transfer` — PASS
- `pnpm run test:demo-adapter` — 15/15 PASS
- `pnpm run test:working-copies` — 3/3 PASS
- `pnpm run test:period-grid` — 9/9 PASS
- `pnpm run test:statement-contract` — 3/3 PASS
- `pnpm run test:transfer-routes` — 5/5 PASS (**35/35 total**)
- Browser: Chromium `152.0.7977.64`; Node `24.13.0`; pnpm `10.26.1`
- Long-period rendering trials (harness-inclusive ms): 60Q `[303.7, 266.6, 274.1]`; 80Q `[333.4, 306.8, 338.0]`; 120Q `[610.6, 608.6, 633.6]`. These are not production or user-perceived performance benchmarks.
- Main suite result JSON: `generated-artifacts/i19-correction-evidence/i19-full-suite-browser-results.json`. Representative 320px Chromium screenshots and earlier viewport screenshots are in `generated-artifacts/i19-correction-evidence/`.
- Transfer build was served on temporary `127.0.0.1:4174` for browser testing only. No public URL was tested.

## Remaining limits

- Axe, Firefox, WebKit, physical iOS Safari, screen-reader, full WCAG/contrast certification, and host OS clipboard remain **UNTESTED**.
- No production API, auth, CSRF, CAS, persistence, real Run, financial formulas, reconciliation, or lender decision was introduced. These remain `NEEDS_GITHUB_VERIFICATION`.
- Project/contract/facility display state is tested as local demo state; fixed statement/KPI outputs remain shared synthetic references and do not recalculate.
- Design freeze is eligible for **source-delta review**, not production integration approval.
