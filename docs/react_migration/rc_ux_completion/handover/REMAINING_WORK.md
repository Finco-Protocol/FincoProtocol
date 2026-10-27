# Remaining work (ordered) — estimates are working time, not measured

## P0 — make the branch consistent and green (≈3–5 h)
1. `git fetch origin && git merge origin/main` into `integration/rc-ux-completion-v1` (merge commit). Resolve the 3 governance-test conflicts (keep both sides). Rebuild bundle, `python3 docs/react_migration/rc_ux_completion/handover/tools/refresh_pins.py`, rerun `tests/test_rcux_governance.py tests/test_rcm_governance.py tests/test_model_mutation_security_successor.py tests/test_model_react_overnight_b_governance.py`.
2. Mount `react_import` in `react_rcux.py`; extend `test_rcux_governance.py` for the narrow POST exception; run `tests/test_model_react_rcux_import_v1.py`; add `tests/model_react_rcux_import_acceptance.py` (star-import into the consolidation role + governance ACCEPTANCE tuple) and run it.
3. Full consolidation role run; triage the failures: lost-request wizard test, the 2 unnamed ones, the 3 Inputs-height tests (pre-existing → U01 compaction or report).
4. Commit → push → update PR #394 body → check GitHub Actions on the exact head (mandatory workflows) and fix on the same PR.

## P1 — Addendum A React-only navigation (≈4–6 h)
* Navigation map document (old target → React route) in `docs/react_migration/rc_ux_completion/NAVIGATION_MAP.md`.
* React Trust view (certificate + validation) over the same read-only artefacts; remove the two classic hrefs and the allow-list. Historical statements: React view or honest "not released" state.
* Audit redirects after Create/Save/Run/Clone; dead tabs; breadcrumbs; contextual menus; empty/error states.
* New browser test `tests/model_react_rcux_navigation_acceptance.py`: walk every rendered nav target (tabs, financing/analysis subtabs, library cards, wizard, Save→Run→Results, Scenario→Compare→History, Financing→Sponsor→Reporting), reject `staging.finco.one`, any non-React same-host route (`/v2/workbook*`, `/library`, `/projects`, `/login` loops excepted), broken links, redirect loops; deep link + refresh, Back/Forward, unsaved-changes guard, 320/390/768/1440 viewports, three themes, feature-gated screens show a React unavailable state.

## P2 — Remaining audit gaps (≈8–12 h)
R4 verify; R7 indexation/start-date fields; R20 period revenue preview; R22 override depth; R23 boundary-date suggestions; R11/R12 reporting (trust artefacts, credit/IC pack in React); R14 Compare Projects; R15 diagnostics heatmap/quality score; R16 OPEX Y1–Y30 table; R17 construction-start derivation; R21 Year-0 toggle; R28 repro; F02 (project-type labels), F05 (duplicate unit in labels), U01 (compact Inputs), U02 (governance details collapsed); R5/R6 financing/sponsor/reserve UI now that FIN-V2 (#391–#393) is on main; R8 stream types/stress (XL — may need owner decision to defer). R19/R24–R27 and G01 = deferred/owner decision with reasons in the register.

## P3 — Evidence (≈2 h)
Update `RC_UX_MASTER_GAP_REGISTER.csv` (+ADD-A/ADD-B rows, evidence locations, commit shas), fill `02_PARITY_MATRIX.md`, four-vertical matrix (Solar/Wind/Data Center/EV), CI report, screenshots (`shots/`), final handover. 15 Addendum-B journeys across 4 verticals, empty and populated Library.

## Definition of done
Every register row CLOSED or INTENTIONALLY DEFERRED/BLOCKED with owner-visible reason; zero Legacy navigation targets; browser role + Python suites green; all mandatory exact-head GitHub checks green; no engine/financial edits; Save≠Run/CAS/CSRF intact. Then, and only then, final line: `READY FOR INDEPENDENT CHATGPT REVIEW — NO SELF-MERGE`. Production acceptance on app.finco.one needs a separately authorised deployment.
