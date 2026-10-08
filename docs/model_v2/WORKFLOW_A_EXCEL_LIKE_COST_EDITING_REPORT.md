# Model V2 — Workflow A: Excel-like CAPEX / OPEX editing

Base: `main` at `f763ba214e1dafa45ac071453ce13b4c8e3b3562` (after #221, #222, #223).
Branch: `feat/model-v2-excel-like-cost-editing`. One consolidated Draft PR.
Parallel Workflow B (Financing & Bankability) owns `sheet_senior_debt`, `sheet_investor`,
`sheet_overview`, `overview_projection`, `output_metric_projection` and `app/v2/router.py`:
**none of those files, nor `post_run_ui.py`, `workbook.html` or `field_editor.html`, is touched.**
Zero diff in `financial_engine/**`, `finco_core/**`, Radar, Yield, Protocol; no schema, CI or
deployment change; no financial formula, tax, debt or waterfall change.

## 1. What was delivered

| Item | Status |
|---|---|
| Compact grid rows (`Code / Description / Driver / Amount [/ Escalation] / Source / State / Actions`, 32 px) for every persisted CAPEX and OPEX line | done |
| Direct-cell editing: click selects the value, typing replaces it (no Ctrl+A → Delete → type) | done |
| Enter commits + advances, Shift+Enter backwards, Escape discards, Tab / Shift+Tab across cells, Arrow Up/Down (numbers ±step, Shift ±10×; text cells move rows) | done |
| Row-level swap: a save replaces only its row and the dependent totals; focus, scroll, open groups and other rows' uncommitted typing survive | done |
| One write per committed edit (Enter + blur never double-submit); serial save queue (each save needs the previous save's fresh tokens) | done |
| Saving / Saved / Failed / Unsaved state per row, `aria-live` | done |
| Failure handling: typed value kept, failed row never re-submitted by blur, queued edits are not replayed against the cause of a failure, **no automatic retry after a genuine 409** | done |
| Run waits for (and first saves) uncommitted edits; structural actions likewise | done |
| Duplicate line (existing typed `add` command) | done |
| Deactivate / Reactivate (#222) preserved; groups, scroll and focus restored after the structural swap | done |
| Data Center B.08 sheet value at non-reference capacity (application layer) | **fixed** (§5) |
| Reset a line to reference | deferred (no per-line reference authority is persisted) |
| Bulk Paste TSV | deferred (needs a new atomic multi-row CAS command; a partial bulk write would bypass CAS) |
| Editable drivers | not offered: the model has no persisted per-line driver; the Driver column shows the calculated kEUR/MW (CAPEX) and "Fixed kEUR/yr" (OPEX) only |

## 2. Changed files

* `app/templates/v2/partials/sheet_capex.html`, `sheet_opex.html` — grid row macros (one form per row), ids for the
  derived regions refreshed with a saved row, feedback region, authority element carrying the next tokens,
  `plain_num` (exact short numeric text), `data-exact` (untouched numbers are submitted with their exact stored value,
  never the rounded display text).
* `static/js/workbook_v2.js` — cost-grid controller (appended IIFE): selection, key handling, dirty/queued/saving state,
  serial queue, token sync, view restore after structural swaps, Run / structural gating, `beforeunload` guard.
* `static/css/workbook_v2.css` — compact grid, state colours (fixed-light surface, own foreground), shared column template
  for header/group/total rows, mobile stacking.
* `app/ui/project_context.py` — Data Center B.08 taken from the effective inputs; per-year steps honoured in the flat
  OPEX detail (the canonical `OpexItem.step_changes` meaning).
* Tests: `tests/test_cost_grid_editing_browser_v1.py` (30 real-Chromium tests), `tests/test_cost_grid_reconciliation_v1.py`
  (25), assertions updated where the old markup was asserted as text: `tests/test_staging_acceptance_a.py` (form located by class token), `tests/test_ev_charging_browser.py` and `tests/test_data_center_browser_acceptance.py` (a line description is now an input value), `tests/test_correction_a_required_gates.py` (editable cells show the exact stored amount instead of a `.0f` rounding).
* No change to `app/v2/*_router.py`, `*_commands.py` or persistence: the existing guarded commands (composite hash,
  workbook version, `row_version`, owner scope, protected reference) are the only write path.

## 3. Save pipeline

`Enter` → `commitRow` → queue → `form.requestSubmit()` → htmx `POST /v2/{capex,opex}/line/update` →
the server re-renders the sheet through the unchanged renderer (all existing OOB stale/run-control updates included) →
the client keeps only `hx-select="#row"` plus `hx-select-oob` for the derived ids (totals, parent summary, group headers,
category totals, KPI/contingency/runtime/projection regions, feedback, authority). After settle the client copies the
authority tokens into every `content_hash` / `workbook_version` input (this also repairs other sheets' stale tokens).
No financial value is computed in the browser.

Honest note: the server still renders the whole sheet for each save (≈200–240 KB response); only the client swap is
row-level (≈4 KB of DOM replaced instead of ≈170–210 KB). Measured in Chromium (10 consecutive edits per sheet,
local, not a CI threshold): median Enter→saved 353–437 ms, max 490 ms.

## 4. Keyboard / pointer matrix (real Chromium, `tests/test_cost_grid_editing_browser_v1.py`)

| Behaviour | Test |
|---|---|
| Click + Ctrl+A + type replaces, **10/10** (CAPEX and OPEX) | `test_ctrl_a_then_type_replaces_the_value_ten_out_of_ten` |
| Ten keyboard-only edits (type, Enter, type, Enter …) none lost, exactly 10 writes | `test_ten_consecutive_keyboard_only_edits_none_lost` |
| Enter ↓, Shift+Enter ↑, Escape discards and sends nothing | `test_enter_advances_shift_enter_goes_back_escape_discards` |
| Tab / Shift+Tab across cells; leaving the row (also from an action button) commits once | `test_tab_and_shift_tab_move_…` |
| Arrow keys ±1 / ±10 / −1; text cell Up moves rows | `test_arrow_keys_adjust_numbers_…` |
| OPEX escalation cell persisted | `test_opex_escalation_cell_is_editable_and_persisted` |
| Enter + Enter + blur = exactly one write | `test_enter_then_blur_sends_exactly_one_write` |
| Focus, scroll position and open groups stable; focus lands on the next row | `test_focus_scroll_and_open_groups_are_stable_after_a_save` |
| A save replaces only its row; other dirty rows keep their typing | `test_a_save_replaces_only_its_row_…` |
| Invalid number: no request, "Enter a number" | `test_invalid_number_is_rejected_locally_and_sends_nothing` |
| **Genuine concurrent modification → Failed, value kept, nothing overwritten, no automatic retry, explicit Enter then succeeds** | `test_genuine_conflict_is_reported_…` |
| Failed row is not re-submitted by blur | `test_failed_row_is_not_resubmitted_by_blur` |
| Save → **Stale** → Run → **Current**; totals follow the server and equal a fresh render (CAPEX, OPEX) | `test_save_marks_stale_then_run_makes_current_…` |
| Same flow for Solar, Wind, Data Center, EV (CAPEX and OPEX, 8 cases) | `test_every_technology_edit_by_keyboard_stale_run_current` |
| Run with an uncommitted edit saves first, then runs | `test_run_with_an_uncommitted_edit_saves_first_then_runs` |
| First save after a scenario switch has **no false 409** (#223 preserved) | `test_first_save_after_a_scenario_switch_has_no_false_409` |
| Deactivate / Reactivate keep groups open and persist; Duplicate | `test_deactivate_and_reactivate_…`, `test_duplicate_…` |
| Reference project has no editable cell | `test_reference_project_is_read_only_no_inputs` |
| Editing one cell never rounds another stored value (Wind OPEX 41.666…) | `test_editing_one_cell_does_not_round_…` |

## 5. Reconciliation and Run / Export parity

* `tests/test_cost_grid_reconciliation_v1.py`: for Solar / Wind / Data Center / EV, at 20 MW and 40 MW, CAPEX and OPEX, the
  sheet total equals the canonical folded input total, before an edit, after an edit, after deactivate and after
  reactivate (25 tests). For OPEX the reference B.13 contingency row (see §7) is excluded from the comparison.
* **Defect found and fixed (application layer):** for Data Center the OPEX sheet kept the *template* B.08 power amount
  (reference capacity) — at 40 MW it showed 8,769 kEUR/yr while the Run uses 17,537.5 (`annual_power_cost_keur`, canonical
  authority), understating the sheet OPEX Y1 (28,169 vs 36,937.5). B.08 is now taken from the effective inputs; the yearly
  columns follow the item's per-year steps. 3 of the new tests fail on the previous code and pass now. The Run's economics
  are unchanged (display only).
* #222 regression authorities unchanged and green: `test_cost_workspace_parity_v1.py` (canonical export reproduces the
  exact Run inputs, 40 tests), seeded OPEX replacement, old-Run STALE detection, immutable Run History, Reactivate CAS /
  ownership / protected reference (`test_cost_workspace_consistency_v1.py`).
* Solar / Wind OPEX after the #222 double-count correction: Y1 237.5 / 458.3 kEUR (seeded at 40 MW), Run total OPEX
  7,568.8 / 16,121.5 kEUR — unchanged by this workstream.

## 6. Safety and isolation

Working Copy becomes STALE after an economic edit (browser-tested); the committed Last Run and Run History are never
touched; reference projects render no inputs and the commands still reject them; owner scoping unchanged. #223's
scenario-switch token synchronisation is untouched and a browser test covers the first save afterwards.

## 7. Known gaps / deferred

* **Solar / Wind OPEX B.13 contingency:** the sheet's "OPEX Y1 (incl. contingency)" adds the reference contingency rate
  (+1.9 % Solar, +6.1 % Wind) although the Run's inputs for seeded Solar/Wind user projects contain no contingency item
  unless a typed B.13 % is set (Run total OPEX 7,568.8 = the line inputs only). Not changed: it is a contingency-authority
  decision, not a presentation fix. Data Center and EV show no such difference.
* The server renders the full sheet per save (client-side row swap only).
* Reset-to-reference per line and Bulk Paste TSV deferred (§1).
* The year-projection table is refreshed as a region and re-opens expanded.
* Category-level (legacy) field editors, add-row forms and the contingency form keep their previous interaction.

## 8. Test results (local, Linux)

* Full public suite on Python 3.12 (CI dependency set) under the bounded supervisor, before the last test-assertion fix:
  **8435 passed, 52 skipped, 1 failed** (`test_correction_a_required_gates … edit_and_reload_via_http[solar]`, an assertion on the
  old rounded `value="52"` display; updated, 3/3 pass); `PYTEST_MAIN_RETURNED` and a normal interpreter exit.
* Real Chromium: 30 grid-editing tests, 259 (productivity, cost workspace, parity, OPEX mobile) passed, EV / Data Center browser
  acceptance passed after the assertion update.
* Pre-existing in this environment and unrelated (also fail on clean `main` `f763ba2` under the same conditions):
  `test_ui_protocol_shell` NVDA / API-placeholder tests (3), `test_DC_HTMX_WORKING_COPY_WORKFLOW`,
  `test_golden_flow_b_reference_to_working_copy_causal_run_reopen`.

## 9. Correction A (browser CI, B.13 truthfulness, acceptance-test integrity)

### 9.1 Protocol UI Browser Acceptance (run 37838621968)

`test_reference_driven_correction_a_23_capture_journey` clicked `seed_row.locator("summary")` on the OPEX
row; the grid row is a form with no `details/summary`. Journey rewritten for the new product behaviour (not skipped,
not weakened, no obsolete markup restored): the persisted row is located by `form[data-cost-row="opex"]` /
`data-testid="opex-custom-row-<id>"`; description and amount are edited through the inline inputs
(Ctrl+A, type, Tab, type — nothing is sent while moving inside the row), committed with Enter, with exactly one guarded
`POST /v2/opex/line/update` (200); the swapped row shows the new description, `data-original` and `saved` state; the
database row has the new label/amount, `source = user_override` and **identical `replay_metadata`** (immutable
reference-seed identity); capacity is changed; OPEX is reopened and label, amount and seed identity are re-asserted.
All 23 screenshots of the inventory are still produced; the Radar/Model capture remainder is unchanged.

### 9.2 B.13 authority trace (Solar / Wind)

* Factory Solar and Wind reference `ProjectInputs.opex` have **no** contingency item; seeded user projects
  (aggregate `User provided year 1 operating expense` replaced by seeded lines) have none either.
* Engine evidence (`test_engine_applies_no_contingency_to_the_reference_unless_it_is_typed`): the factory reference run equals a
  run on its own items; adding an explicit 6 % raises total OPEX by exactly 6 %.
* Therefore the 2 % (Solar) / 6 % (Wind) figures are **a reference-only informational estimate** (presentation constants in
  `app/ui/project_context.py`), not an effective cost. The only way contingency enters a user project's Run is a
  **typed B.13 %** (project value or scenario override) via `apply_opex_contingency`.
* Application-layer correction (no engine, no formula, no input change): when the effective inputs carry no contingency
  item and no typed B.13 % exists, the sheet's contingency rate is 0, totals equal the canonical inputs, the label reads
  "Total OPEX" (not "incl. contingency"), and the reference estimate is shown separately:
  *"Reference contingency estimate: X% — not applied: it is excluded from the totals above and from the model's economics."*
  With a typed B.13 % (or a scenario override) it is applied, labelled "(incl. contingency)", and equals the Run's inputs.
  Data Center and EV (reference rate 0) are unchanged. Factory/reference-project pages keep their legacy presentation (not
  user projects; not Run).
* The earlier reconciliation test no longer divides the contingency out: sheet total == canonical total, unadjusted.
* `tests/test_cost_opex_b13_authority_v1.py` (12): no override (Solar, Wind: sheet = Run inputs, note shown, no hidden
  contingency item), explicit override (applied, no note, Run + export parity), Data Center / EV unchanged, deactivate /
  reactivate before and after a Run, scenario B.13 override (sheet = Run, export parity), engine fact. Two of them and the
  Solar/Wind reconciliation cases fail on the previous presentation code.
* `tests/test_f06_opex_display_authority.py` encoded the same wrong premise ("the engine computes the contingency", the
  anchor "misses" it): two premise tests were corrected to the verified facts (anchor == canonical total on an untouched
  reference; divergence demonstrated with a *typed* contingency); the four assertions on the summary field following the live
  VM authority are unchanged.

### 9.3 Acceptance-test integrity

Changed assertions versus `main` (all other lines of those files untouched): `test_staging_acceptance_a.py` — the form is
located by class token and the Deactivate fields are read from the row form that the button includes
(`hx-include="closest form"`), then posted unchanged to `/v2/capex/line/deactivate`; `test_correction_a_required_gates.py` —
`.0f` rounding → exact stored value (stronger); `test_data_center_browser_acceptance.py`, `test_ev_charging_browser.py` —
description asserted as the **input value** (stronger than the previous "text anywhere"). New real-Chromium evidence
(`test_cost_grid_editing_browser_v1.py`): the Deactivate button POSTs `…/line/deactivate` (never `update`) exactly once with
the correct `project`, `sub_line_id`, current `row_version`, current composite `content_hash` and `workbook_version`; the row
becomes inactive (soft state, amount untouched) and leaves the active totals; Reactivate restores row and total; a stale
identity fails closed with the error banner, no mutation and no retry; an uncommitted edit is saved before a Deactivate runs;
untouched decimals are not rounded when another field is edited. Cross-owner and protected-reference rejection plus stale CAS on
the command endpoints remain covered by `test_cost_workspace_consistency_v1.py`; the reference project renders no inputs
(`test_reference_project_is_read_only_no_inputs`).
