# WF-1A — SC-3 Working Copy recovery

Base main `8944aca351ef89c81a8a9bf715ab352629c35624`.

## Reproduced facts (Stage A, on main)
* A persisted draft value the canonical adapter refuses to build (reproduced with `capex_epc_contract_keur = -20000.0`, a value that B1 now refuses at Save but that legacy data can still hold) makes the *input builders* fail, not the stored data: `/v2/workbook` answered an uncontrolled error and React `/v2/model-react/inputs` answered 503. Other React sections (workspace, library, statements, runs, scenarios, diagnostics, trust, fields, cost lines, revenue) kept answering 200.
* The Working Copy owner had no repair path: an unrelated single Save worked, an unrelated grid Save was refused with `BATCH_STALE_CONTENT` (the page that issues the tokens could not render), and the faulty field could not be reached.

## Root cause
Every full-page and projection builder materialises `ProjectInputs` from the draft. `build_projectinputs_from_snapshot` raises `SnapshotInputError` for a value the adapter refuses; nothing handled that error at the page/route boundary, and the only Save path (registry field Save) was reachable only from the page that failed to render.

## Implemented (SAFE ENGINEERING CORRECTION)
* `app/workbook/draft_recovery.py` (new): `diagnose_draft(snapshot)` — read-only. Returns `None` for a readable draft; otherwise up to 25 `RecoveryIssue`s (snapshot key, registry field id when the key is an editable registry scalar, label, unit, stored value, reason, `repairable`). It never writes, corrects, clamps, rounds or discards, and never runs the model.
* `app/v2/router.py` `v2_workbook`: after the composite-identity build, an unreadable draft returns the new `workbook_recovery.html` page (HTTP 200, read-only, no Run, no Save side effect). The page posts a plain form to the **existing** `/v2/workbook/update` with the existing operation-bound `workbook-update` token and composite CAS. Healthy drafts take the unchanged code path.
* `app/v2/react_workspace_router.py` `/model-react/inputs`: unreadable draft → HTTP 409 typed `WORKING_COPY_RECOVERY_REQUIRED` payload carrying the issue list, the operation-bound grid-save token and composite CAS (`save` is `null` for a protected reference).
* React: `RecoveryPanel.tsx`, `WorkspaceView.tsx`, `api.ts`, `types.ts`; the bundle `static/react/finco-react.js` is rebuilt from source (`npm run build`, copied; `git diff --exit-code -- static/react` clean after the rebuild).
* Repair is a **deliberate user Save of a valid value** through the existing route; any other value is refused by the registry/adapter exactly as before. No automatic correction, no implicit Run after Save or recovery.

## Not implemented / deferred
* Non-registry unreadable keys are *reported* but marked not repairable from this view (no new write path was created).
* Nothing in D-029 (reservations, idempotency, fencing, Run commit/history) and no change to the canonical Run endpoint.

## Evidence
* `tests/test_fin_val_b2_c1_recovery_finite_opex.py::TestLegacyRecovery` (8 tests) and `::TestReactRecovery` (5 tests): recovery page without mutation or history; repair then readable; two issues repaired one at a time; invalid replacement (`-5`, `abc`, `nan`, `inf`) refused with the stored draft unchanged; stale CAS / forged / missing / cross-session tokens refused; other user and anonymous get no detail; protected reference never repairable; React typed state, repair with the returned token and CAS, refusal matrix, non-disclosing 404 for another user, healthy contract unchanged.
* Live-server Chromium check (disposable database, desktop 1440×1000 and mobile 390×844, legacy and React): recovery rendered, invalid value refused with the stored value unchanged, valid value repaired, page/grid readable afterwards, no page error, no horizontal scroll, zero Runs created.
* B1 test `test_stored_invalid_snapshot_is_not_rewritten_by_this_change` is updated: it previously asserted the HTTP 500; it now asserts the recovery page and that the stored value is still byte-identical.

## Policy decisions / risks
* The two routers and the OPEX template are pinned by the SEC-02 successor inventory; see `SECURITY_GOVERNANCE_AND_D029_CONFLICT_MATRIX.md` (this is the open governance dependency of the PR).
* A draft with *many* unreadable values lists the first 25 (`complete=false`); the owner repairs and reloads.
