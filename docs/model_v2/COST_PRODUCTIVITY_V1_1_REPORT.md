# CAPEX / OPEX Productivity V1.1 — existing-code gap audit and scoped implementation

Base: `main` at `607db110928859bf37f6dde1195e50c4b80cde12`. Branch `perf/model-cost-productivity-v1-1`.
This is V1.1, not a new CAPEX/OPEX V1: nothing below re-implements functionality that exists on main.
Live check at start: no open PR touches CAPEX/OPEX, cost editing, `grid_router`, or `workbook_v2.js`
(open PRs are Radar/Yield work and dependency bumps).

## 1. DONE / PARTIAL / MISSING matrix (from the code on main, not PR descriptions)

| Capability | Where it lives on main | Status |
| --- | --- | --- |
| Cost templates / seeded line items (#194) | `docs/model_v2/COST_TEMPLATE_CONTRACT.md`, `reference_seed_service`, `capex_sub_lines` / `opex_sub_lines` `source='reference_seed'` | DONE |
| Dense cost workspace (#211) | `.v2-cost-row` grid (`workbook_v2.css`), compact Code / Description / Driver / Amount / Source / State / Actions row (`sheet_capex.html::custom_row`, `sheet_opex.html::opex_custom_row`) | DONE |
| CAPEX/OPEX lifecycle: deactivate, reactivate, inactive block (#221) | `capex_commands.deactivate_capex_line/reactivate_capex_line`, `opex_commands.*`, `capex_inactive_block` | DONE |
| Cost workspace consistency (#222) | `tests/test_cost_workspace_consistency_v1.py`, `_parity_v1.py`, `_reconciliation_v1.py` | DONE |
| Scenario-switch CAS token sync (#223) | `#v2-scenario-edit-authority`, scenario `afterSettle` sync and `syncTokens` in `workbook_v2.js` | DONE |
| Excel-like direct-cell editing (#225) | `workbook_v2.js` cost-grid block: Enter/Shift+Enter/Esc/Tab/arrows, `data-exact` exact-value preservation, one guarded save per committed row, serial queue with fresh tokens, no auto retry of a failed economic write, open groups / scroll / focus restore | DONE |
| Row-level guarded Save | `capex_router /line/update`, `opex_router /line/update` → `capex_commands._exclusive_tx` (BEGIN EXCLUSIVE + composite CAS + dirty hash in one commit) + `update_sub_line(row_version)` | DONE |
| Atomic batch of SCALAR fields (#239) | `WorkbookUpdateService.apply_batch_draft_update` → `v2_atomic_batch_draft_update` | DONE (scalars only) |
| Input Grid (#245) | `grid_router`, `input_grid_projection`, `inputs_grid_v1.js` | DONE (scalars; line-item categories are shown read-only with "edit on the CAPEX/OPEX sheet") |
| Workspace consolidation (#248) | five-group navigation, `prb-*` browser evidence | DONE |
| Atomic multi-row reorder of lines | `reorder_sub_lines` (all rows version-checked in one transaction) | DONE (precedent that a row-versioned multi-row transaction is safe) |
| **Atomic multi-row Save of persisted cost LINES** | each committed row is its own transaction; N edits = N requests, N token round-trips, partial success possible | **MISSING → implemented here** |
| Verbose provenance / calibration notes | suppressed in the standard view (`# Calibration/development notes suppressed …`) | DONE |
| Driver / amount / source / state visibility | dedicated cells per line row (Driver, Amount, SOURCE badge, state, "edited since Last Run" mark) | DONE |
| Category expansion consistency | open groups are preserved across saves; no defect evidence found | DEFERRED (no evidence) |
| Input Grid ⇄ cost-sheet navigation for line-item categories | by design read-only + pointer; making line items editable in the Input Grid is a separate authority decision | DEFERRED |

## 2. The gap and why a safe minimal extension exists

Multi-row editing of persisted line items had no atomic path: ten edited cells meant ten independent
`BEGIN EXCLUSIVE` transactions (each with its own CAS round-trip), so a failure at row 6 left rows 1–5
saved. The scalar C0 writer cannot be used (it owns `ProjectInputSet` fields, not `*_sub_lines` rows), and
looping the row commands would be sequential writes, not an atomic transaction — neither is done.

What makes a genuine atomic extension possible without new financial authority:

1. Both command layers already run their repository call inside one shared kind of transaction
   (`_exclusive_tx`: BEGIN EXCLUSIVE, composite-identity CAS, `dirty=1` + new hash in the same commit, ROLLBACK on any exception).
2. The repository writers `capex_sub_lines.update_sub_line` / `opex_sub_lines.update_sub_line` take the caller's
   cursor, own no transaction and are conditional on `row_version` (`updated_at`).
3. The composite identity already covers CAPEX lines, OPEX lines, the draft and the scenario, so one CAS protects the whole batch.

## 3. Implementation (scoped; no new authority)

- `app/v2/cost_batch_commands.py` (new): `update_cost_lines_batch` applies N existing-line updates inside ONE
  `_exclusive_tx`. Shape validation first (1..50 lines, no duplicates, finite numbers, non-empty descriptions);
  inside the transaction EVERY line is verified (exists in THIS project, active, submitted `row_version` equals the stored one)
  before the first write; unknown / foreign-project / inactive / stale lines are reported per line and nothing is written.
  Escalation and notes default to the stored values. It imports no engine, no scalar writer and runs nothing.
- `app/v2/grid_router.py`: `POST /v2/workbook/grid/cost-lines/save` (session ownership, CSRF, protected-reference guard, owner
  check, 50-line bound, payload size bound). Success returns the re-rendered sheet plus the SAME post-Save out-of-band refresh as a
  single-row save (toolbar/strip STALE state, run controls with the new CAS token, `HX-Trigger` token propagation on OPEX).
  Failure is a JSON 4xx (403 reference/CSRF, 409 stale hash/version or stale/unknown lines, 422 invalid) that htmx does not swap.
- `sheet_capex.html` / `sheet_opex.html`: an optional, default-OFF "Stage edits, save together" bar (toggle, count, Save staged, Discard, message).
- `workbook_v2.js`: staged mode inside the existing cost-grid block. Off: byte-for-byte the existing per-row autosave.
  On: a committed row is marked `staged` (nothing sent); **Save staged** posts all staged rows once (CAPEX and OPEX together),
  exact stored values for untouched numbers, inputs made read-only while the request is in flight (no keystroke can be lost),
  the other sheet is refreshed so no row carries a stale version, open groups / scroll / focus use the existing swap-view restore.
  On any failure every typed value stays on screen, rows are marked failed with the server's per-line reason, and there is NO automatic retry.
  Run and structural actions are refused (with a message) while edits are staged; toggling staged mode off is refused while edits exist.
- `workbook_v2.css`: staged row state and stage bar.

## 4. Financial authority impact

None. No `financial_engine/**`, `finco_core/**`, persistence schema, scalar C0 writer, ProjectInputSet, Run, Run History, export or
governance pin changed. Save never runs the model, never writes Run History or the Last Run; the workspace becomes dirty with a new
composite hash, so the canonical freshness authority classifies the Last Run STALE and CURRENT only returns after a canonical Run.

## 5. Evidence (local, synthetic disposable working copies)

`tests/test_cost_batch_save_v1.py` (24): Solar / Wind / Data Center / EV Charging — ten edited lines (6 CAPEX + 4 OPEX) persist exactly,
untouched rows byte-identical, scalar draft untouched, Last Run + Run History unchanged, new CAS token returned; each of non-finite /
empty description / duplicate / stale row version / unknown line rolls back every row; stale composite hash and stale workbook version
rejected without writes; a concurrent single-row edit gives a genuine 409; an injected failure after partial writes rolls back rows, hash
and dirty flag; foreign-project line is `ROW_NOT_FOUND` and the other project is byte-identical; reference project, foreign owner, anonymous,
forged/empty CSRF refused; deactivated line refused; scenario token staleness refused then accepted with the fresh token; Solar and Wind:
Save → STALE, restore exact originals, canonical Run reproduces the first Run's economic outputs exactly; single-row commands still work
with the token returned by a batch; the batch module imports no financial authority.

`tests/test_cost_batch_save_browser_v1.py` (11, real Chromium + uvicorn, event-driven waits): ten staged cells in each of the four verticals
produce zero row autosaves, nothing persisted before Save, exactly one request, exact stored values; failure of one row (concurrent writer)
rolls back all rows, keeps typed values, marks rows failed, and issues exactly one request (no retry); open groups, scroll and staged mode
survive the Save; a CAPEX+OPEX batch is one request and a following single-row autosave has no false 409; staged mode off keeps the existing
autosave; Run is refused while staged; 390 px layout has no horizontal scroll.

Measured (local, synthetic, click → "Saved" confirmation, no fixed waits): 10-line Save 0.35 s Solar, 0.35 s Wind, 0.40 s Data Center,
0.46 s EV Charging. For comparison only, the existing per-row path for the same ten edits from first keystroke to idle took 7.07 s on Solar
(it includes typing and ten serial requests). These are local numbers, not staging or CI figures.

## 6. Remaining limitations

- Staged mode is opt-in per session (toggle resets on a full page load by design).
- A genuine 409 keeps the typed values but needs a reload to obtain fresh tokens (no silent retry).
- Add / duplicate / deactivate / reactivate / reorder stay single-command operations.
- Input Grid still shows line-item categories read-only; making line items editable there is not part of this change.
- Cost line routes outside this new endpoint remain without CSRF (pre-existing, pinned known gap); the new endpoint is CSRF-protected.
