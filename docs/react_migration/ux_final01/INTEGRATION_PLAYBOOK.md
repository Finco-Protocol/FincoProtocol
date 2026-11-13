# UX-FINAL-01 — integration playbook (public-safe)

## Upstream state (re-read live before every integration; these are observations, not authority)
- Accepted `main`: `b1c08e2d00fe9933565d253d5cee6e5849b143e1` (tree `5b25c1f245d3d53d9bbe24060c13dc936e06b8d7`), observed 2026-11-13.
- #444 (C06): Draft, head `48a81c2f9b6a6f0cbd36caf4f6e701d0335ee065`, base = the same `main`. Its PR body mentions another head; the API head is authoritative.
- R04 Phase 1 (#442): merged, ISOLATED (not wired into Save/Run). R04 Phase 2: no PR observed.
- #446 (this work): Draft, branch `claude/new-session-awc9gz`, base `main`.

## What must NOT be merged or copied from a Draft
Nothing from #444 (writers, profile routes, successor pins) may be copied into #446 while #444 is a Draft. R04 Phase 2 semantics (annual absolute quantities,
global caps, CfD behaviour, selected-case calculations, Save All/Run) must not be shown as active before the server route exists and is proven.

## #444 (C06) integration, after it is genuinely accepted into main
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
