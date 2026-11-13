# UX-FINAL-01 — work completed ledger (public-safe; no private screenshots or client material)

Authoritative per-screen status: `screen_contract.csv` (same directory). This ledger explains what was done, where, and how to re-verify it, so a later
agent can resume without re-investigation. Draft PR: #446 (branch `claude/new-session-awc9gz`). Never relabel DEPENDENCY_PENDING as DONE.

## How to re-verify (reuse, do not rebuild)
- Fast checks: `cd frontend && npm run typecheck && node --test src/app/financing/pr3b1/__tests__/*.test.mjs src/app/financing/pr3b2/*.test.mjs`
- Screens at 1440/1024/768/390/320, NOT_RUN and with a real Run (synthetic generated project):
  `PYTHONPATH=. UX_FINAL01_SCREENSHOT_DIR=<private dir> pytest -q -p no:cacheprovider tests/ux_final01_screens.py` (`UX_FINAL01_ROUTES`, `UX_FINAL01_FULLPAGE=1`).
  It builds a TEMPORARY bundle and fails on page-level horizontal scroll, one-character-per-line text and script errors.
- Slice-1 browser test: `tests/test_ux_final01_browser.py` (Financing NOT_RUN, five viewports). Not run by any hosted browser role.
- Toolchain used: Python 3.12 venv (`pip install -r requirements.txt -c constraints.txt -r requirements-ci-tests.txt` then `playwright==1.63.0`), Node 22.

## Delta log
### 2026-11-13 — slice 1 (committed; PR #446 opened)
- Delivered and REUSED from now on: Financing inputs unit beside label (`financing/pr3b2/FinancingEditing.tsx`); NOT_RUN banner without the repeated raw code
  (`financing/pr3b1/runEvidence.ts`); five-viewport synthetic browser test; screen contract; finite exact-source successor `tests/ux_final01_scope.py`
  (+ `tests/test_ux_final01_scope.py`, 121 cases) after R04, with literal handoffs into the older scope tests.
- Correction A: the tautological `P.supersedes(...) is False or ... is True` assertion was replaced by the real forwarding contract (R04 owns no bundle pin;
  it supersedes the bundle only by forwarding to this successor and only for the exact current pin; stale/zero/foreign blobs refused; forged successor
  manifest confers nothing). The bundle-bytes test was renamed to state it proves pinned identity only; reproducibility is the separate clean-build gate.
- Measured (not guessed): the UX scope module is 121 cases / ~97 s locally (one 32 s whole-chain check, ~100 cases at 0.5-1.1 s). Hosted shard-0 (which holds
  R04, UX, `test_ci_v4_governance_gate`, `test_ci_v4_release_gate`, `test_rc_sec_csrf_successor`, post432) ran >22 min on `ad5d3f61`; the 13 governance-scope
  modules of this PR are UNWEIGHTED in `docs/ci_v4/module_weights.json`. `test_rc_sec_csrf_successor` is 24 s on this branch vs 46 s on main (no regression).
  CI timeout work is deliberately deferred to the final stabilization (owner override).

### 2026-11-13 — checkpoint UI A/B (this commit; coded, typechecked, 90 node tests pass; browser verification pending)
| Item | Before | Now | Paths | Invariants kept |
|---|---|---|---|---|
| Chrome chip | repeated the Run state (NOT RUN YET / RESULTS UP TO DATE) next to the bar badge | names the data origin only (`SAVED PROJECT DATA`) | `app/WorkspaceView.tsx` | `data-origin-chip="canonical-run"`; bar still shows Saved/Staged/Run state and last Run id |
| Inputs intro | four stacked lines (shortcuts disclosure, Last Run disclosure, two sentences) | one `.ux-intro` row | `app/InputsOverview.tsx`, `app/WorkspaceView.tsx` (shortcuts passed as `tools` prop), `styles/ux-final01.css` | every `data-ci-*` attribute and sentence; `.ux-input-tools` class and summary text; NOT_RUN keeps `—` KPIs |
| Financing banner | `CURRENT · CURRENT — selected Last Run…` | state shown once | `financing/pr3b1/FinancingOverview.tsx`; test `readLayer.test.mjs` | gate state/reason values unchanged |
| Financing field grid / units | inline styles (slice 1) | scoped CSS classes `.pr3b2-cap`, `.pr3b2-fields` | `styles/ux-final01.css`, `FinancingEditing.tsx` | same fields, writers, save paths |
| Revenue assumptions labels | broke one character per line | sheet-editor grid cells >= 360px | `styles/ux-final01.css` | no value/writer touched |
| Phone project bar | ~340px before content | compact grid of the three actions (CSS) | `styles/ux-final01.css` | all controls and data attributes; 44px touch targets |

(The two open defects listed here earlier are now fixed; see the second checkpoint below.)

### 2026-11-13 — checkpoint UI A/B/C (second commit after a651a229)
Status vocabulary per item: CODED / BROWSER-VERIFIED / SOURCE-BYTE-INTEGRATED / HOSTED-CI-VERIFIED. Nothing below is SOURCE-BYTE-INTEGRATED (the bundle is not rebuilt)
or HOSTED-CI-VERIFIED (governance/bundle red by design until consolidation).
| Item | Paths | CODED | BROWSER-VERIFIED | Evidence / note |
|---|---|---|---|---|
| CAPEX Monthly rows 206px tall at <=768px (REAL defect) | `styles/ux-final01.css` | yes | yes (harness: pre-fix 7/8 probes fail, post-fix 8/8 pass; visual before/after) | sticky label 278px/85% of phone viewport + editor cell 116px; page height 390px 4037 -> 2799px; root cause: `.rcm-table th,td{white-space:nowrap}` + `.pr2b-editor` min-width 0 + `overflow-wrap:anywhere` |
| Debt metrics Covenant monitor Metric column crushed (REAL defect) | `styles/ux-final01.css` | yes | yes (same proof, 1024/768/390/320, NOT_RUN and Run) | row-header cell now min 11rem; "No value is configured..." note wraps at words; chart data table cells nowrap, scroll inside `.dm-scroll`; >640px card layout untouched |
| Financing single navigation row | `app/financing/FinancingStudio.tsx`, `styles/ux-final01.css` | yes | NO (pending acceptance regression) | contracts preserved, see screen_contract.csv |
| Financing run banner shows state once | `app/financing/pr3b1/FinancingReadLayer.tsx` | yes | NO | |
| Results KPI tile density (>=700px) | `styles/ux-final01.css` | yes | NO | |
Observation (not a defect of this PR): Debt metrics shows `1.19999999999x` / `-0.000000000007x` for the sculpted sizing target. `app/debtmetrics/format.ts` deliberately refuses to
display a value as exactly equal to its reference when it is not ("never a trailing-zero look-alike"); left unchanged.
Harness lessons (keep): (1) `tests/ux_final01_screens.py` exclusion of hidden elements must match only the absolutely-positioned, 1x1, overflow-clipped sr-only pattern; an earlier
broad version treated a 0x0 `display:contents` wrapper as hidden and silently PASSED the pre-fix broken layout. (2) Always re-prove "fails pre-fix, passes post-fix" after changing the harness:
temporarily drop the fix block from `ux-final01.css`, run `-k "not 1440"` on `UX_FINAL01_ROUTES=inputs/capex/monthly,debt-metrics`, restore.

## Governance state (read before pushing more)
`tests/ux_final01_scope.py` pins slice-1 bytes. This checkpoint changes pinned files and the CSS, so the governance gate, the served-bundle identity step and the
CSS pin are RED by design until the single consolidation step at UI stabilization (owner override). Do not regenerate the successor per screen. The CSS bundle
(`static/react/finco-react.css`) is pinned in the eight current maps and closed over by F03/F04 on registry+JS keys only; moving it requires releasing or
extending those frozen modules (see INTEGRATION_PLAYBOOK.md). `static/react/finco-react.{js,css}` has NOT been rebuilt for this checkpoint.

## Not done / pending (see screen_contract.csv)
Financing one-workspace layout; CAPEX/OPEX presentation work; OPEX "uniform across lines" label: VERIFIED CORRECT (conditional on all lines sharing one rate), no router change made (see screen_contract.csv);
Revenue read structure (R04 Phase 2 gated); Overview/Results compact KPI consistency; five-viewport QA of the new CSS; private continuation ZIP; Croatian report.
