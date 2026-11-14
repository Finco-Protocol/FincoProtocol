# UX-FINAL-01 — integration playbook (public-safe)

## Upstream state (re-read live before every integration; these are observations, not authority)
- Accepted `main`: `07f558461dc13c1a8c623064360dee0b4ba42cd0` (tree `d3c7bcf2c24f8557b7977cb3dea85816ac15ed2a`), after "Merge PR #444" (C06, head `0a9f4fe41a1d3e88114eeef5cb2a1bc01a69a95d`); observed 2026-11-13. Previous main: `b1c08e2d00fe9933565d253d5cee6e5849b143e1`.
- #444 (C06): MERGED. R04 Phase 1 (#442): merged, ISOLATED. R04 Phase 2: not in `main`, no PR observed.
- #446 (this work): Draft, branch `claude/new-session-awc9gz`; merge commit `fdb2616b` = ordinary merge of `07f55846` into `abffe583`.

## What must NOT be merged or copied from a Draft
#444 is now merged: its accepted code arrives only through the ordinary merge of `main`; nothing was copied from a Draft. R04 Phase 2 semantics (annual absolute quantities,
global caps, CfD behaviour, selected-case calculations, Save All/Run) must not be shown as active before the server route exists and is proven.

## #444 (C06) integration - DONE on this branch (kept as the procedure; see the ledger for evidence)
1. `git fetch origin && git merge origin/main` into the #446 branch (ordinary merge; no rebase, squash or force push). Resolve conflicts by hand.
2. Expected overlap: `frontend/src/app/capex/*`, `editing/CostLinesGridView.tsx`, `WorkspaceView.tsx`, `static/react/finco-react.{js,css}`, `tests/fin_v2_cohorts.py`
   and the eight current maps. #444 and #446 currently carry competing finite successors on the SAME accepted R04 base: the #446 successor must be re-derived as a
   compatible finite successor AFTER the accepted C06 successor (predecessor history and negative tests preserved; historical manifests byte-identical).
3. CAPEX: wire the monthly M1..Mn read layer and added-line profile UI to the accepted route response shapes only; verify `CAPEX_PROFILE_LEAF_UNKNOWN` (orphan
   fails closed), profile-only Save vs amount Save, CAS/409, scenario ownership; re-run Save/Reload/Run acceptance at 1440 and 390.
4. Acceptance IDs: AC-07, AC-08, AC-09 (plus AC-03/AC-11 density). Exit: those rows in `screen_contract.csv` move from DEPENDENCY_PENDING with evidence.

## R04 Phase 2 integration, after it is accepted
Prepare (already structurally possible): Revenue/PPA read layout in `frontend/src/app/workflow/PPAEditorView.tsx` / `PpaContractsEditor.tsx` (R04 Phase-1 baseline pins
these; changing them needs a reviewed successor). After merge: wire annual absolute quantity and global cap inputs to the accepted canonical contract; keep
legacy volume-share behaviour, no duplicate physical energy for CfD, merchant price zero NOT hidden. Required: business oracle + Save All/Run tests. AC-16/17/18.

## Exact-source successor order (final consolidation only)
1. Stabilize UI bytes. 2. Rebuild `static/react/finco-react.{js,css}` from a clean install (`npm ci --ignore-scripts && npm run build`), copy, `git diff --exit-code static/react`.
3. Re-derive ONE finite successor: sources, JS bundle and CSS bundle pins. Moving the CSS pin requires handling the F03/F04 frozen modules' closure
   (they close over registry+JS keys only) — extend them by reviewed literal substitutions, do not repin blanket. 4. Keep every negative tamper/restore test.
5. Re-measure test cost (`--durations`), weigh the 13 unweighted governance modules via a measured corrective change coordinated with the #444 CI fix; a cancelled or
   timed-out shard is never PASS. 6. Six hosted workflows on the final exact head. 7. Independent Fable review.

## Business tests to run after each integration
F04 browser (`tests/test_f04_financing_browser.py`), mandatory consolidation role (`tests/test_model_workspace_consolidation_browser.py -k "financ or pr3b"`),
`tests/ux_final01_screens.py`, node unit tests, governance gate (`python -m tools.ci_v4_governance_gate --output <file>`), scope suites.

## Open product/policy items (do not invent)
OPEX annual writer absent; P90 writer absent; Base rate + Margin not a persisted writer; the server-supplied OPEX escalation label "uniform across lines" was VERIFIED CORRECT
(it is conditional on all lines sharing one rate; otherwise "mixed / varies by line"); no router change is needed.

## CI triage of #446 head `6c04befa` (2026-11-13) — classification, not acceptance
Six mandatory workflows: PASS Governance Full History, Dependency Security Audit, Protocol UI Browser Acceptance; FAIL CI V4 PR, PR Compile and Safety Gate, FIN-VAL F01.
The public-safety step PASSED on this head (the earlier "forbidden identifier" finding was a false semantic collision in one ledger line and is reworded; scanner/denylist untouched).
- PR Compile and Safety Gate: fails ONLY the served-bundle identity step (`git diff --exit-code static/react`): sources and stylesheet changed, the committed bundle is deliberately not rebuilt yet. Class: expected exact-source/bundle drift.
- FIN-VAL F01 (137 passed / 3 failed): all three are exact-source governance checks (cohort composite invalid; mutation-security inventory lists the changed pinned files as unreviewed blobs). No numeric F01 assertion failed. Class: expected exact-source drift (not a proof of numeric safety either).
- CI V4 shards (per-test JUnit): shard-0 78 failed / 421 passed (R04 scope 38, UX scope 29, post432 7, CI V4 scope 2, rc_sec 2); shard-1 37 / 472 (T01-E 19, F03 8, R02 6, 4 chain-dependent); shard-2 148 / 589 (perf 58, F04 45, R03 28, BESS02 15, 2 chain-dependent).
  Every failing test belongs to the governance / exact-source family; zero numeric, financial or UI-behaviour failures; zero unresolved. Class: expected exact-source drift until ONE consolidation.
- Timing: all three shards finished in <= 6m08s and nothing timed out. The earlier 15-25+ minute shards were the governance chain PASSING (long exact-source work); with invalid pins the cohorts exit early. Do not read the short runtime as health.
- CI V4 `f01` browser job (separate from the F01 workflow) fails its "Four-vertical real browser rate round-trip" step; classification pending a log read at consolidation (likely the same exact-source dependency; not assumed).
The owner-flagged stale status vocabulary in `tests/test_ux_final01_scope.py` is fixed: one closed vocabulary (CURRENT, CODED, BROWSER_VERIFIED, SOURCE_BYTE_INTEGRATED, HOSTED_CI_VERIFIED, PARTIAL, DEPENDENCY_PENDING, BLOCKED, DO_NOT_CHANGE, MISSING) with a validator and negative tests (PASS/DONE/COMPLETE, case/padding variants, structural forgeries).

## Post-#444 integration record (2026-11-13) - how the successor chain is wired (public-safe)
1. `git merge origin/main` (ordinary). Conflicts were only governance/generated files; resolved to the accepted `main` bytes, then the UX successor was re-derived over BASE = `main` by `git show BASE:path` + literal one-occurrence substitutions (the module refuses an ambiguous or missing anchor).
2. Chain: ... -> R04 -> C06 -> UX-FINAL-01. C06 has one forward hook; U1/U2/PR1/PR2b/PR2c/PR3b1 have one bounded deferral each; the registry appends this cohort once; exact-tail tests and C06's own mutation tests accept one more state.
   The C06 module is stored with CRLF line endings: its substitutions are CRLF literals.
3. Re-derivation checklist after ANY change to a pinned file: rebuild the bundle from a clean install, regenerate the successor, run `python -m tools.ci_v4_governance_gate`, then the scope modules; never hand-edit a pin.
4. Cost: see the ledger. A rebalanced `docs/ci_v4/module_weights.json` is the proper fix for shard imbalance and is an owner/CI decision (frozen by C06).
5. Workflow run identifiers belong to the pull request description and the final report (a pinned file cannot name its own commit's runs); the two living documents may change without a pin.
