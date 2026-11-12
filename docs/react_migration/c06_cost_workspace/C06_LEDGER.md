# C06 — Cost workspace: added-line CAPEX profiles and OPEX yearly truthfulness (Draft)

Base: accepted `main` `2cce0343d55dd8865fe8bf5a59f5beebc40b5b9c`. No financial rule, writer, schema, flag, selector, weight or workflow is changed.
`FINCO_SAVE_ALL_PROFILE_ENABLED` stays OFF (OD-B2 pending); `FINCO_G10_RUN_OPEX_PANEL` stays OFF. Synthetic data only.

## Outcome

| Area | Status | Basis |
|---|---|---|
| CAPEX profile on a user-added line (`C.NN.U###`) | **PARTIAL — source COMPLETE, served bundle + exact-source successor `INTEGRATION_BLOCKED`** | Reproduced on current main: backend + engine already support it end to end (G-U2-1, merged); only the browser withheld it. Browser now offers the same shape / `Edit % / month` as native lines, driven solely by the server's item list. |
| OPEX Year 1…N per row | **already shipped (#427–#429), unchanged**; one honest note added | Inline Years column is the server's read-only saved-line projection; Last Run all-in OPEX is a separate, flag-gated panel. |
| OPEX annual-value editor | **`OWNER_POLICY_BLOCKED / CANONICAL_WRITER_MISSING`** | A saved OPEX line is label + Year-1 amount + one escalation %; no annual-vector writer exists, so none was built and no escalation formula was invented. The UI now says so (`data-opex-years-edit="canonical-writer-missing"`). |

## What changed (4 source files, 2 test files)

- `frontend/src/app/capex/ProfileDraftProvider.tsx`, `ProfileRowEditor.tsx`, `profileFocus.ts`, `frontend/src/app/editing/CostLinesGridView.tsx` — added lines are editable exactly when the server lists them; truthful note about retiring a profiled line; OPEX read-only/no-writer note.
- `frontend/src/app/capex/__tests__/userLineProfile.test.mjs` — draft→wire→document pipeline with an added-line key, month-count and 100 % rules, absence of the old blocks, no annual editor.
- `tests/test_c06_custom_capex_profile_replay.py` — real-app replay: add line → catalogue → Save → dirty/STALE identity → real Run (14 monthly periods reconcile) → reload → two rows with decimal percents → rename → zero amount → stale CAS → retire (Run refused `CAPEX_PROFILE_LEAF_UNKNOWN`, document and history untouched) → wrong month count → foreign code.

## Observed behaviour (current main, executed)

Added line is eligible; Save persists the document under its code; composite identity moves; Run uses the monthly axis; rename keeps the code and profile; a profiled line set to zero still Runs; a stale token is refused with nothing written; retiring a profiled line stops the next Run with a typed refusal and leaves the document intact (no silent drop, no re-assignment); wrong month count and foreign/unknown codes are refused before any write.

## Unresolved owner approvals (not decided here)

1. **O-G-U2-1 residual risk.** The profile document stores the line *code*, not `sub_line_id`. The app has no hard-delete path and the code counter skips retired rows, so a code is only reusable after a manual database hard-delete. Closing it needs `sub_line_id` in the persisted document: a schema change and a separate Financial Owner decision. Not done.
2. **OD-B2** (atomic Save All with profile): flag stays OFF.
3. **B-09** catalogue expansion (the 506 source rows not in FINCO) and any annual OPEX writer: separate engine/owner decisions. The 24 subtotal/calculated source lines must never become editable items.

## `INTEGRATION_BLOCKED` — single-integrator inventory

The served React bundle and the exact-source successor chain are shared with R04 (#442) and F04. Source edits here change files pinned by these cohorts, so the CI V4 governance gate, the React bundle identity check and the browser/F01 jobs are expected RED on this Draft until one integrator sequences them. Nothing was rewritten, skipped or bypassed.

- Regenerate `static/react/finco-react.js` + `.css` from this source (`npm run build`, copy `dist/finco-react.*`); the build from main's source is byte-identical to the committed bundle, so the diff is exactly this change.
- Pinned paths touched: `frontend/src/app/editing/CostLinesGridView.tsx` (fin_v2_wf06a, wf06b, u1, u2, ux_pr1, ux_pr2a, ux_pr2b); `frontend/src/app/capex/ProfileDraftProvider.tsx` (ux_pr2b, ux_pr2c); `ProfileRowEditor.tsx` (ux_pr2b); `profileFocus.ts` (u2); both bundle files (every cohort that pins them, incl. f03/f04).
- New files need a successor cohort: the two test files above and this ledger.
- Registering the browser acceptance for the added-line profile in the mandatory consolidation role is a shared governed file and was not touched.

## Known pre-existing failure (not caused by this change)

`frontend/src/app/editing/__tests__/editing.test.mjs` → "staging records old/new, counts per section, and equal-to-baseline clears the edit" fails identically on clean main.
