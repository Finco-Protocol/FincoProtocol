# Iteration 15 — Full React source harvest checkpoints

Scope: the existing isolated FINCO Design sandbox only. The intended future frontend is a complete React + TypeScript + Vite application. Legacy Jinja2/HTMX remains a reference until a separately authorized migration; no production integration is performed here.

## Preflight

- Local branch `main`, HEAD `f935e04`; working tree clean before Iteration 15 changes.
- No competing FINCO test/build process was visible.
- Canvas inspection found three live FINCO frames: `finco-library`, `finco-workspace`, and `finco-results`. A separate generic artifact frame is not a FINCO screen.
- Latest saved I14 evidence reports browser 17/17, working-copy 3/3, adapter 11/11, period-grid 9/9, typecheck/build PASS. These are prior-run results; Iteration 15 must run fresh verification.
- The I14 source audit identified a Project Library landmark-test blind spot: the smoke check accepted zero `<nav>` elements because `[].every(...)` is true. This is a reproducible test defect and an actual missing Library navigation landmark.
- `axe-core` is not installed. Full screen-reader/WCAG and OS clipboard checks remain outside the evidence available here.

## Checkpoints

| Workstream | Status | Evidence / remaining |
| --- | --- | --- |
| W1 Architecture and harvest inventory | PASS (design inventory) | Updated `INTEGRATION_READINESS.md` and `DESIGN_HARVEST_MANIFEST.md` for the selected full React+TypeScript+Vite frontend; mapped current routes/components and labeled production contracts `NEEDS_GITHUB_VERIFICATION`. No GitHub access. |
| W2 Typed presentation boundary | PARTIAL | `StatementWorkbook` accepts typed `snapshot`/`status` props from `statementContract.ts`; `test:statement-contract` 2/2. Its fixed fixture and URL/presentation state remain in the component; InputGrid/CostLinePlanner fixture separation is not complete. |
| W3 Single React composition | PASS (internal proof) | Hidden query route uses one React root and lazy-loads the three existing exported pages. Browser composition case passed; no fourth Canvas frame or production SPA/API was created. |
| W4 Cross-copy isolation | PASS for tested same-tab synthetic state | Browser test exercised Reference plus copies A/B across scalar, PPA-A/B/C, Senior A/B, Junior, SHL, Equity, Base scenario, CAPEX/OPEX, Save and same-tab reload. Fixed result fixtures remain shared; new-tab/server persistence is not tested. |
| W5 Accessibility and responsive | PARTIAL | Named Library breadcrumb and browser smoke checks passed; visible control names and F2/Esc focus return verified. Real 1440/900/390 route checks, 390px mobile copy/trace, sticky/internal scrolling and no page overflow passed. No axe, screen-reader, full WCAG or OS clipboard test. |
| W6 Fake adapter robustness | PASS for test-only fake transport | `test:demo-adapter` **12/12**; includes simulated 422 validation and earlier conflict/read-only/stale/zero-vs-unavailable cases. Not wired into visible UI or a real backend. |
| W7 Fresh QA and handoff | PASS for recorded sandbox scope | Fresh typecheck/build PASS; `test:browser` **18/18**, working copies **3/3**, period grid **9/9**, statement contract **2/2**, adapter **12/12**, `git diff --check` PASS. Three original FINCO frames verified live; details and limits are documented below. |

## Final verification checkpoint

- Browser suite: `pnpm --filter @workspace/mockup-sandbox run test:browser` — **18/18 PASS, 0 FAIL** after the final route-composition and test-harness edits.
- Unit suites: `test:working-copies` **3/3**, `test:demo-adapter` **12/12**, `test:period-grid` **9/9**, `test:statement-contract` **2/2**.
- Fresh `pnpm --filter @workspace/mockup-sandbox run typecheck` passed. Fresh `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build` passed (65 modules; build 1.29s). `git diff --check -- artifacts/mockup-sandbox` passed.
- Chromium screenshots and structured output are stored as `test-evidence/i15-*.png` and `test-evidence/iteration-15-browser-results.json`. Harness-inclusive 60/80/120Q samples are in the JSON; do not treat them as production performance benchmarks.
- Component Preview Server restarted and reported Vite ready. Canvas read-only check: exactly the three FINCO shapes `finco-library`, `finco-workspace`, `finco-results` are live. A separate generic Artifact iframe exists but is not a FINCO frame. No fourth FINCO frame was created.
- No full React production app, real API/provider, financial engine, persistence, auth, GitHub changes, or financial calculations were added. Screen-reader/WCAG, new-tab session behavior and OS clipboard remain untested.

No change is made to the original FINCO application, GitHub, backend, database, engine, CI, staging, production, deployment or publication.

## Iteration 16 — Full React transfer RC1 checkpoints

| Workstream | Status | Evidence / remaining |
| --- | --- | --- |
| W1 Standalone React assembly | PASS for isolated entry | New transfer entry uses one React root, typed routes/context, lazy imports of the three existing pages, loading/unavailable/error states. No new Canvas frame or production API. |
| W2 Typed presentation boundary | PARTIAL | Library defaults are separated into a fixture module and can be supplied via props. Results accepts an external fixed synthetic statement/status provider. InputGrid/CostLinePlanner already expose controlled typed props. Some page state and PPA/facility fixture types remain coupled/unwired. |
| W3 Full React composition/build | PASS | `build:transfer` independently emits `dist-transfer/index.html`; browser tested Library→Reference→Working Copy→Save→Results, Back/Forward and unavailable route. |
| W4 Fake adapter contract | PASS for existing fake scope | Existing adapter tests 12/12 PASS. It remains test-only; no real auth/API/canonical save or engine. |
| W5 Accessibility/responsiveness | PARTIAL | Three original preview routes passed 1440/900/390 no-document-overflow checks; transfer routes passed widths 1440/900/390; keyboard, focus and sticky checks passed in the full suite. Axe, screen reader, full WCAG and OS clipboard remain UNTESTED. |
| W6 Source package | PASS | Curated source-only ZIP created and integrity-tested. Contents and exclusions are listed in `FINCO_REACT_TRANSFER_RC1_REPORT.md`. |
| W7 Fresh QA/evidence | PASS for tested design scope | Typecheck, standard build, transfer build, 5 unit suites (31 checks), browser suite (19 checks) passed. Canvas state shows the three original FINCO frames live. |

### Iteration 16 final evidence

- Workspace revision observed: local HEAD `26ade41`; no GitHub operation, push, PR, deployment or publish was performed.
- `pnpm --filter @workspace/mockup-sandbox run typecheck` — PASS.
- Standard Vite build and separate `build:transfer` — PASS.
- Unit tests: demo adapter 12/12; working copies 3/3; period grid 9/9; statement contract 2/2; transfer routes 5/5 (31/31).
- Chromium/CDP `test:browser` — **19/19 PASS, 0 FAIL** after test-harness corrections. Current JSON and screenshots use `test-evidence/iteration-16-browser-results.json` and `test-evidence/i16-*.png`.
- Canvas read-only state: `finco-library`, `finco-workspace`, `finco-results` all live. The generic Artifact iframe is unrelated; no fourth FINCO frame was created.
- Historical evidence caveat: the first I16 smoke attempts wrote three prior I15 evidence paths. Those paths are not pristine I15 history; use the I16 records instead (documented in `BROWSER_ACCEPTANCE.md`).
- Transfer decision: **FULL REACT TRANSFER RC1 READY as a design-only, source-only package**. Production migration remains blocked on independent GitHub verification of canonical service contracts and explicit authorization for a separate integration task.
