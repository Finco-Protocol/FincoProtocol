# Iteration 18 progress

Date: 2026-10-21

Scope: isolated GoldenNiceConsultant FINCO Design sandbox only. No production integration, GitHub work, publish/deploy, financial calculations, backend, or authentication changes.

## Workstream status

| Workstream | Status | Evidence / remaining |
| --- | --- | --- |
| W1 — Automated accessibility | **PARTIAL / UNTESTED** | Existing accessible-name/landmark checks and keyboard tests ran. axe tooling is absent; no axe scan or screen-reader certification. |
| W2 — Keyboard/focus semantics | **PARTIAL** | Added skip link and explicit keyboard activation for custom-routed controls. Keyboard skip/main and multiple workbook paths passed, but end-to-end trace-return did not reach the return target within 100 Tab presses. |
| W3 — Cross-browser | **UNTESTED** | Only Chromium exists in the environment; Firefox and WebKit were not installed. |
| W4 — Clipboard/paste | **PARTIAL / PASS in Chromium API** | Valid TSV, undo, and atomic invalid-date rejection passed using Chromium Clipboard API. Host OS clipboard remains untested. |
| W5 — 320px / long grid / visual | **PARTIAL** | 320px Chromium emulation and no-document-overflow checks passed; long-grid timings recorded with harness overhead. Current I18 screenshots cover 320px; no screenshot diff baseline or physical-device Safari test. |
| W6 — portable component boundaries | **PARTIAL** | Existing visual components kept unchanged in structure; keyboard handlers and focus behavior improved. No broad provider refactor or real API adapter was added. |
| W7 — QA and RC3 package | **NO-GO** | Fresh typecheck/build PASS; unit suites 34/34 PASS; browser suite 20/24 PASS, 2 FAIL, 2 UNTESTED. RC1/RC2 checksums unchanged. RC3 ZIP not produced because acceptance failed. |

## Fresh verification

- TypeScript typecheck: PASS.
- Design Vite build: PASS.
- standalone transfer build: PASS.
- demo adapter: 15/15 PASS.
- working copies: 3/3 PASS.
- period grid: 9/9 PASS.
- statement contract: 2/2 PASS.
- transfer routes: 5/5 PASS.
- Browser smoke: 20/24 PASS, 2 FAIL, 2 UNTESTED (exit code 1).
- All results remain synthetic demo behavior, not financial validation.

## Remaining blockers

1. Latest copy-isolation browser smoke timed out waiting for the Inputs grid after creating a session copy; earlier I17 tests passed the broader isolation matrix, but current acceptance is not clean.
2. Keyboard-only trace-return flow did not reach the return target within 100 Tab presses. The dedicated Iteration 12C debt/trace test passed, but this new full route remains unaccepted.
3. No axe, Firefox/WebKit, screen-reader, WCAG certification, or host OS clipboard evidence.

Decision at the initial I18 checkpoint: **RC3 BLOCKED / design QA freeze not granted.** This historical disposition is preserved; see the correction record below.

## I18 Correction A / I19 verification

- Reproduced the copy-isolation failure as an opaque-origin test setup bug: session storage was cleared before the browser navigated from `about:blank`. The harness now navigates to the preview origin first; fresh Copy A/B browser case passed.
- Reproduced the trace failure: every statement value was a separate Tab stop, making the statement-source link unreachable within the existing keyboard path. Statement cells now use one roving tab stop; arrow navigation remains within the table, keyboard help is exposed, and trace return restores focus to the selected cell. Desktop and 390px keyboard-only regression passed.
- Full browser suite: **22/24 PASS, 0 FAIL, 2 UNTESTED** (axe and Firefox/WebKit unavailable). Browser evidence: `generated-artifacts/i19-correction-evidence/i19-full-suite-browser-results.json`.
- Fresh unit suites: adapter 15/15; working copies 3/3; period grid 9/9; statement contract 3/3; transfer routes 5/5 (**35/35**). Typecheck, Design Vite build and transfer build: PASS.
- RC1/RC2 checksums remain unchanged. Any RC3 package and clean-extraction result are recorded in `FINCO_REACT_I18_CORRECTION_A_I19_REPORT.md`.
- Full screen-reader/WCAG/axe, Firefox/WebKit and host OS clipboard remain UNTESTED. This evidence is not production financial validation or backend integration.

Updated disposition: both I18 P0 browser failures are corrected and all runnable browser cases pass; the remaining two cases are tool-unavailable checks, not passing checks. See the linked correction report for the honest source-harvest decision.
