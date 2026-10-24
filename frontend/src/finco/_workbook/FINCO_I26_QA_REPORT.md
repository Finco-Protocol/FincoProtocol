# FINCO Model — Iteration 26 QA and recovery report

**Scope:** the isolated FINCO React design sandbox only. All financial examples remain fixed synthetic data. This report describes browser-tab demo state, not server persistence.

## Result

**PASS for the exercised Chromium and unit/build scope; one browser-engine case remains untested.** Source parent before this closeout: `b416ad13fe6babbf98d82ec5373a4b328c90e997`. The final source revision is the ordinary I26 closeout commit recorded in Git history; this report avoids embedding its own commit hash.

## Delivered behavior

| Situation | User-visible behavior verified |
| --- | --- |
| Browser storage read/write unavailable | A persistent, accessible warning explains that local drafts/copies may be lost on navigation, reload, closing the tab, or clearing browser data. No durable server copy is implied. |
| Create Working Copy cannot be verified | The action announces a plain-language failure, stays on the Reference, and leaves the Reference unchanged. |
| Local input Save fails | The typed value remains visible and marked unsaved; the UI does not acknowledge Save. |
| Discard write fails | The in-app Stay/Leave dialog stays open, retains the exact draft, announces the error, and returns focus correctly when the user chooses Stay. |
| Last Run metadata write fails | The UI does not navigate to Results or claim a successful/current Run; prior fixed example outputs are unchanged. No financial Run occurs. |
| Browser storage is healthy | A locally verified Save can be reopened in the same tab while session storage is available. This is not durable persistence. |
| Working Copy is missing on re-entry | The route becomes a read-only recovery state with a visible link back to Project Library. |
| Protected Reference | Shared workbook module surfaces receive read-only state and disable editable fields; PPA fields and Save were checked as disabled and unfocusable in Chromium. Existing Input Grid/cost-planner reference checks also pass. |

No browser-native `beforeunload` dialog was added. A clean draft does not trigger an intrusive prompt. A real close/reload may still lose local state.

## Verification evidence

- **Unit tests:** nine focused suites, **66/66 PASS**: demo adapter 15, storage helper 5, working copies 9, period grid 9, statement contract 7, results contract 7, Insight 5, plain-language status 3, transfer routes 6.
- **TypeScript:** `pnpm run typecheck` PASS.
- **Builds:** `PORT=5000 BASE_PATH=/ pnpm run build` PASS (89 modules); `PORT=5000 BASE_PATH=/ pnpm run build:transfer` PASS (82 modules).
- **Full browser suite:** `test-evidence/i26-final-browser-results.json` — **42 PASS / 0 PARTIAL / 0 FAIL / 1 UNTESTED of 43**. Only Firefox/WebKit is untested because those browser engines are unavailable. No uncaught browser errors, `console.error`, or native browser dialogs were captured.
- **Focused I26 suite:** **4/4 PASS** in the final full run: blocked storage/copy failure at 320px; failed Save/discard at 390px; failed Last Run metadata write; successful local Save/re-entry and missing-copy recovery.
- **Transfer build serving:** the browser harness started a temporary local static server over `dist-transfer`. Chromium verified HTML, JavaScript and CSS responses/MIME, SPA deep-link fallback, reload, local demo Save, Results navigation, Back/Forward and 1440/900/390/320 responsive paths. No network service or dependency was added.
- **Axe-core:** version 4.14.0 reported zero violation entries across nine scanned states. Ten incomplete checks were recorded across scans that returned incomplete-rule counts; I26's two scans checked for serious/critical findings and recorded no violation entries. Full WCAG and screen-reader support are not certified.
- **Screenshots:** the full suite physically produced 58 PNGs in `test-evidence/`. I26 captures: `i26-final-storage-warning-320.png`, `i26-final-storage-save-failed-390.png`, `i26-final-storage-discard-dialog-390.png`, `i26-final-storage-discard-failed-390.png`, `i26-final-storage-run-failed-390.png`, `i26-final-storage-normal-save-reload-390.png`, `i26-final-storage-missing-copy-390.png`.
- **Canvas:** `finco-library`, `finco-workspace`, and `finco-results` are the three original frames and are live. The Results frame was refreshed in place after the live route was visually confirmed; no fourth frame was created.

## Acceptance corrections and test history

An initial full browser attempt recorded 40/43 PASS, 2 FAIL, 1 UNTESTED. Investigation found harness defects, not a reproduced FINCO UI defect:

1. The production-transfer test fetched the Vite development fallback page instead of the built transfer bundle. The existing assertion had never been intended to accept a dev shell; it now serves `dist-transfer` from a temporary local HTTP server and checks the real assets/MIME and deep links.
2. A reference-copy test still expected the old reload wording. It now asserts the actual safety copy: same-tab restoration is conditional on available browser storage, and copies can be lost on leaving, reload, closing the tab, or clearing browser data.

No test was skipped or weakened. The final complete configured run is the 42/43 result above. Earlier focused debugging runs are retained in the evidence directory but are not counted as final acceptance.

## Remaining limits

- `sessionStorage` is browser-tab-local; private-mode behavior can differ by browser. No server persistence, auth, cross-device recovery, or guaranteed restoration is implemented.
- No real finance calculation, Save, Run, result lineage, or lender decision is performed.
- Firefox/WebKit, physical Safari, assistive-technology/screen-reader testing, full WCAG audit, and host OS clipboard remain untested.
- Axe includes incomplete checks and does not establish accessibility certification.

## Evidence paths

- Full JSON: `test-evidence/i26-final-browser-results.json`
- Focused I26 PNGs: the seven files listed above under `test-evidence/`
- Updated acceptance: root `BROWSER_ACCEPTANCE.md` and this `_workbook/BROWSER_ACCEPTANCE.md`
- RC10 overlay instructions/checksums: root `FINCO_RC10_DELTA_README.md` and `generated-artifacts/FINCO_RC10_DELTA_MANIFEST.json`
