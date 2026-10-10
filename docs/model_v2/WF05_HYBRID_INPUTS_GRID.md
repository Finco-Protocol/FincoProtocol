# WF-05 — Hybrid Inputs hub + grid editing (V1)

Presentation layer only. No financial semantics, engine, persistence schema or registry change.

## Navigation
`INPUTS | SCENARIOS | OUTPUTS | ANALYSIS | TRUST` groups the **existing** workbook tabs
(`static/js/inputs_grid_v1.js` → `HYBRID_GROUPS`). Group buttons click the real tab buttons; the sheet
tab bar, the left tree, deep links and `#hash` routing are unchanged, so every tab stays directly
reachable. A new `Input Grid` tab (INPUTS) is the only added sheet.

## Persistent status strip
Project · technology · Working Copy/Reference · scenario, the CURRENT / STALE / NOT RUN state (canonical
freshness; mirrored from the toolbar chip that every save and Run already refreshes out-of-band), the
Last Run time and — independently — the Last Run **Integrity** verdict (PASS / FAIL / UNAVAILABLE from
the Trust Pack integrity evidence). Freshness is never an integrity verdict and vice versa.

## Input Grid
Dense, keyboard-first grid of the registry-bound scalar inputs: CAPEX and OPEX categories whose sheet
offers a scalar editor, plus Project, Revenue and Tax numeric fields.

| Key | Behaviour |
|---|---|
| Enter / Shift+Enter | commit the cell (stage it) and move down / up |
| Esc | cancel the cell edit (back to its last committed value) |
| Tab, ↑, ↓ | move between editable cells (edit committed on leave) |
| Paste | column of values (positional) or `label⇥value` rows; validated by the canonical validator **before** anything is staged — all-or-nothing |
| Ctrl+S / Save changes | ONE atomic batch through the C0 canonical writer |

* `POST /v2/workbook/grid/validate` — dry run of `WorkbookUpdateService.validate_field_update` + technology
  applicability. Persists nothing.
* `POST /v2/workbook/grid/save` — a single `WorkbookUpdateService.apply_batch_draft_update` call
  (`v2_atomic_batch_draft_update`: one `BEGIN EXCLUSIVE`, composite CAS, immutable ProjectInputSet, F3 scope
  checks). All cells persist or none. CSRF + session ownership + protected-reference guard + 50-cell bound.
  The model is **never** executed; a persisted change classifies the existing Last Run STALE.
* `GET /v2/workbook/grid/panel|sheet` — in-place re-render; the client restores the focused cell, caret,
  scroll position and open sections so Save never moves the user.
* Run is refused while grid edits are staged (the user is told to Save or Discard) — never silently saved,
  never silently run.

## Authority boundaries (deliberate)
* **Cost line items** (CAPEX/OPEX sub-lines) keep their existing guarded per-row commands (row_version CAS,
  one write per edited row, direct-cell editing already in `workbook_v2.js`). They are a different
  persistence authority from the C0 field batch and are NOT merged into the batch. Categories whose cost
  comes from line items are shown read-only with a link to the detail sheet — no editor is invented for a
  value the model does not use.
* Capacity and project name (side-effect cascades) and `debt.financing.instruments` (F3 editor) stay
  read-only in the grid, exactly as C0 refuses them.
* Choice/text fields, calculated and template-locked fields are shown read-only with the reason.
* No enable/disable toggles: none exist in canonical persistence.

## Modified-but-not-run markers
* Grid fields: compared with the Last Run **input snapshot** of the same scenario; "Saved · not run" with the
  Last Run value on hover. Not comparable (no Last Run / other scenario / unreadable) → no marker and the
  reason is stated; a marker is never fabricated.
* Cost lines: `●` when the row was written after the Last Run timestamp ("edited since Last Run").
