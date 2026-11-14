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
### 2026-11-13 — verification of the checkpoint above (third commit group)
- Full matrix `tests/ux_final01_screens.py` (11 routes x 1440/1024/768/390/320 x NOT_RUN and Run, synthetic): **10 passed** in 241 s, no page overflow, no one-character text, no collapsed table cell, no script error.
  Earlier runs reported 5 failures that were harness issues (screen-reader-only `fm-sr-only` labels over icon columns: "Row actions", "Download"); the check now measures VISIBLE text only.
- Financing writer/nav regression on the NEW code (new bundle served temporarily, then `git checkout -- static/react`): `tests/test_model_workspace_consolidation_browser.py -k "financ or pr3b"` + `tests/test_f04_financing_browser.py` = **43 passed** in 174 s.
- Phone chrome (CSS): offset above content 410 -> 386 px at 390, 438 -> 414 px at 320. Measured with `UX_FINAL01_EVAL` (see harness), not estimated.
- Node unit tests: 90 passed; `npm run typecheck` clean.
- OPEX "uniform across lines" label VERIFIED CORRECT (conditional on all lines sharing one rate); no router change.
Still NOT SOURCE-BYTE-INTEGRATED and NOT HOSTED-CI-VERIFIED: `static/react/finco-react.{js,css}` is not rebuilt; governance successor, bundle identity and CSS pin are red by design until consolidation.

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
Revenue read structure (R04 Phase 2 gated); Overview/Results compact KPI consistency; five-viewport QA of the new CSS; private continuation ZIP; final owner report (written in the owner's language).

## 2026-11-13 — final polish checkpoint (fourth commit group)
- Mobile header (CSS only): 390px project bar field 819 -> 703 px, title block 539 -> 407 px, top bar 83 -> 51 px; 320px 902 -> 748, 604 -> 433, 112 -> 51. Measured by the harness, before = pushed head 6c04befa.
- Financing evidence inspector: read-only; two panes at >=1360px, stacked below; focus-follows-block; no new write path; Financing regression suites unchanged.
- Results duplicate status removed; status vocabulary of screen_contract.csv is closed and checked by the governance scope test with negative tests.
- Harness gained two checks (overlapping controls, unnamed controls) plus keyboard and high-contrast probes and a self-test. The first run of the new checks reported 9 of 10 failing: one REAL defect (group
  twisty controls stacked at the corner at <=900px; fixed in ux-final01.css) and one harness artefact (the browser restored the previous route's scroll offset, so the sticky project bar sat over scrolled content;
  every route is now judged from scrollTo(0,0)). Thresholds were not loosened. Final matrix: **10 passed** (11 routes x 5 widths x NOT_RUN/Run); other harness tests 5 passed.
- Still NOT SOURCE-BYTE-INTEGRATED and NOT HOSTED-CI-VERIFIED: bundle, successor and CSS pin move only at the single consolidation step.

## 2026-11-13 — post-#444 integration (accepted C06 merged into this branch)
Status levels used below: CODED, BROWSER_VERIFIED (local, synthetic), SOURCE_BYTE_INTEGRATED (committed bundle = clean build of the committed sources; exact-source gate passes),
HOSTED_CI_VERIFIED (all six workflows SUCCESS on one SHA). This section states the highest level each item has evidence for; HOSTED_CI_VERIFIED is claimed only in the final report, never here.
- Refs: accepted `main` moved `b1c08e2d` -> `07f55846` (tree `d3c7bcf2c24f8557b7977cb3dea85816ac15ed2a`, "Merge PR #444"; #444 head `0a9f4fe4`). Merge commit `fdb2616b` has parents `abffe583` (this branch) and `07f55846`; ordinary merge, no rebase/squash/force.
- Conflicts: 20 files, all governance or generated (8 current maps, the cohort registry, 9 predecessor scope tests, `static/react/finco-react.js`). Frontend sources merged WITHOUT a textual conflict (C06 touched CapexStudio, CostLinesGridView, CostWorkbench, compact-inputs.css; this PR touches none of them).
  Resolution: every conflicted file took the accepted `main` bytes; the UX successor was then re-derived AFTER C06 (never by choosing ours/theirs). C06 sources, tests, its manifest and ledger are byte-identical to `main` (asserted by a test).
- Successor design (`tests/ux_final01_scope.py`, base = accepted `main` with C06): pins every source, test, stylesheet and the single JS/CSS bundle this PR changes; registered after C06; C06 gains ONE forward hook (the pattern F04 and R04 used);
  the older cohorts that pinned the frontend files this PR changes (U1, U2, PR1, PR2b, PR2c, PR3b1) gain one bounded line each that defers to the signed chain; U1 lists this cohort among its reconciled successors. Current maps move exactly six keys
  (registry, JS bundle, CSS bundle, U1, U2, PR3b1 scope modules). Two living documents (this ledger and the playbook) may change without a pin; they cannot name the commit that contains them.
- CSS pin: `static/react/finco-react.css` moves through the same finite chain (C06 already owned that key); F03/F04 needed no further edit.
- Local evidence on the merged sources: `python -m tools.ci_v4_governance_gate` PASS (41 cohorts exact, composite valid, zero mutation violations); `tests/ux_final01_screens.py` 15 passed (11 routes x 1440/1024/768/390/320 x NOT_RUN/Run, probes, self-test);
  C06 acceptance on the merged bundle: `tests/test_c06_cost_workspace_browser.py` + `tests/test_c06_custom_capex_profile_replay.py` 9 passed (added line, profile-only Save leaves the staged amount unpersisted, Reload, Run, retired line loses editing, saved profile retained; 1440 and 390);
  `tests/test_c06_cost_workspace_scope.py` 118 passed; typecheck clean.
- Hosted evidence at `5e1d3274`: Governance Full History, Dependency Security Audit, PR Compile and Safety Gate (served-bundle identity from a clean `npm ci`), FIN-VAL F01 and Protocol UI Browser Acceptance all SUCCESS; CI V4: plan, static (governance gate + bundle identity), shard-0 and f01 SUCCESS; shard-1 failed on TWO
  `tests/test_u1_scope.py` checks (U1 did not yet list this cohort as a reconciled successor) - fixed in `2be8435a`; shard-2 was cancelled by the next push.
- CI cost (measured, shard-1, `5e1d3274` vs #444's green run): 6768 s vs 2563 s. `test_u1_scope` 3867 s (#444: 1883 s), `test_ux_final01_scope` 1659 s (new), `test_ci_v4_perf_scope` 262 s (144), `test_ux_pr2b_scope` 215 s (131). Per call this cohort adds ~56 ms to a chain evaluation;
  the U1 test enumerates every later cohort unscoped. Done: this PR's own test module now asserts the whole composite only for representative paths. NOT done (needs an owner decision): rebalancing `docs/ci_v4/module_weights.json` (frozen by C06) or scoping `tests/test_u1_scope.py` (pinned by six other cohorts).
- Observation, not caused here: five frontend node unit tests fail identically on pristine `main` (`wf06a`, `editing` 1, `insights` 3). CI does not run node unit tests (it runs typecheck and build).
- Flags: `FINCO_SAVE_ALL_PROFILE_ENABLED` and `FINCO_G10_RUN_OPEX_PANEL` stay OFF; nothing here activates or claims staging/production acceptance. OPEX Year 1..N stays read-only; no annual writer, P90 writer or Base rate + Margin writer; R04 Phase 2 is not in `main`.

## 2026-11-14 — CI V4 forensics and performance iteration
- Forensics (real plan and JUnit artifacts): shard-2 of the first integrated run never finished (cancelled at 150 min); its F near 45% was a real deterministic failure in `test_r02_ppa_ux_scope` (registry-tail test did not list this cohort); the stall after 83% sat in `test_u2_scope`, whose single node `test_positive_cohort_is_exact_registered_and_closed` took 587 s locally (repeated full cohort verdicts, no deadlock reproduced).
- Fixes kept: the r02 literal state list; one bounded registry call scope around that read-only u2 node (587 s -> 5.4 s, assertions and node id unchanged); this PR's own test module asserts the whole composite only for representative paths (1659 s -> ~80 s hosted).
- Hosted result at `17034827`/`8a1176c5`: shard-2 finished in 15:45 and 21:51 (it was cancelled at 150 min before); F01, f01, static (governance gate + clean-build bundle identity), Compile/Safety, Governance, Dependency Audit and UI Browser SUCCESS.
- Tried and reverted: scoping the read-only nodes of `test_u1_scope` (3 nodes = 2085 s of 3091 s). It requires bounded hooks in four `post413_*` cohorts, which makes CI select `test_post413_o1_scope` (two unscopable nodes of 333 s and 266 s; `test_post413_r18_scope` alone measured 527 s for 18 tests), so shard-1 does not get faster. Net surface and time were worse, so those files are untouched.
- Scheduling authority: the trusted-base selector reads `docs/ci_v4/module_weights.json` from the base checkout; the file weighs `test_u1_scope` at 259 s and `test_u2_scope` at 169 s and has no entry for 17 selected modules. A head-side edit cannot change #446's schedule; a separate trusted-policy successor is the owner decision.
