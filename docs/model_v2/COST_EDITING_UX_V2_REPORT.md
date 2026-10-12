# CAPEX / OPEX editing UX & performance V2

Base: `main` at `86792f12ac9ad6763df0881538e682b0d40ed8bb`. Branch `feat/model-ux-productivity-v2`.
UX / performance only. No change under `financial_engine/`, `finco_core/`, `domain/`, `tests/model_v2_governance.py`
or the CI workflows. No new persistence writer, no change to CSRF, `row_version` or composite CAS.

## 1. DONE / PARTIAL / MISSING (from the code on main, not from PR text)

| Capability | State on main | Status | What this change does |
| --- | --- | --- | --- |
| Dense cost workspace, category collapse, activate / deactivate | `.v2-cost-row`, lifecycle commands | DONE | untouched |
| Direct-cell editing, Enter / Shift+Enter / Tab / arrows, exact-value preservation | `workbook_v2.js` cost-grid block | DONE | reused |
| Esc discards the current cell edit | Esc reset the whole **row** to stored values | PARTIAL | Esc returns only the focused cell to the value it held when entered |
| Single-row guarded Save | `/v2/capex/line/update`, `/v2/opex/line/update` | DONE | kept as the explicit immediate mode |
| Atomic multi-row Save | `/v2/workbook/grid/cost-lines/save` → `update_cost_lines_batch` | DONE (opt-in, per page load) | reused unchanged; now the default |
| Batch editing as the default | opt-in toggle, reset on every page load | MISSING | default on; the explicit immediate choice is remembered for the tab (`sessionStorage`) |
| Staged → Save from the keyboard | button only | MISSING | `Ctrl/⌘+S` inside the cost grid (never the browser "Save page") |
| Visible choice before Run / scenario switch with unsaved edits | message written to the cost sheet's own bar, invisible from other tabs; scenario switch unguarded | PARTIAL | non-modal Save / Discard / Stay notice in the panel being viewed; scenario actions guarded |
| Unsaved edits visible when on the other sheet | none | MISSING | dot + title on the CAPEX / OPEX tab that holds unsaved edits |
| Token coherence across both cost sheets | **defect**: an OPEX save left the CAPEX authority element stale; the next staged Save read it and sent an old composite hash (false 409) | DEFECT | fixed; see §3 |
| Focus after a mouse Save | focus dropped to `<body>` | MISSING | restored to the cell being edited, no scroll jump; Save stays focusable while in flight |
| Keyboard hint on both cost sheets | CAPEX only | PARTIAL | OPEX has the same hint |
| Category-total row | wrapped into a narrow column; a black block in dark mode | PARTIAL | one compact line, legible in light and dark |
| Inputs Grid → cost sheet navigation | section-level "Detail sheet →" and a text pointer | PARTIAL | per-category "Open lines →" opens the sheet, expands the category and focuses its first amount |
| Inputs Grid editing of line-item values | read-only by design | DONE | unchanged; the link is navigation only |
| Auto-compute option | none | MISSING by design | **not implemented**, requirements in §6 |

## 2. Measurement

`tools/bench_cost_editing_ux.py` drives real Chromium against a live uvicorn server on a disposable database, with
synthetic working copies of Solar, Wind, Data Center and EV Charging. Per scenario it reports interaction latency,
request count, per-request server time (time to first byte), response bytes, DOM swap/settle time (htmx
`afterRequest` → `afterSettle`) and focus retention. Each scenario is repeated 7 times after a discarded warm-up, each
repetition from a freshly loaded page, and reported as median with range. "Before" runs the same harness against
pristine `main` in a separate worktree. All numbers are local and synthetic — not staging or CI figures.

Confirmation time stops at the actual confirmation (all rows saved and swapped in; or the "Saved N lines" message);
Playwright's 500 ms network-idle detection is excluded for both modes, and request counts are taken after idle.

Raw results: `docs/model_v2/evidence/cost_ux_v2/before.json`, `after.json`. Tables: `COST_EDITING_UX_V2_METRICS.md`.

What the data says:

* The dominant cost of editing several cells was the per-row path: N edits → N serial POSTs, each returning the whole
  re-rendered sheet (~300 KB) plus a follow-up integrity refresh. Ten mixed edits took ~7 s and 20 requests.
* Batch Save turns that into one POST. It is already measured as the fastest path, so the change is to make it the
  default, not to build another one.
* Per-save server time (~160–280 ms) and swap time (~50–150 ms) are unchanged: nothing about a single save got
  slower or faster, and no engine work happens on Save.
* The two extra GETs after a Save (`financing/integrity`, and `financing/investor` after a batch) are **kept**. They
  render the verdict *paired with the current CURRENT / STALE freshness*, which a Save changes; removing or caching
  them would present a stale value as fresh. Not an optimisation target.
* The extra `grid/sheet` GET for a cross-sheet batch is kept: it brings the other sheet's row versions forward. Folding
  it into the batch response was considered and rejected — it would duplicate the out-of-band run-controls fragment in
  one response.

## 3. A defect found by the baseline

The probe "immediate OPEX save, then a staged CAPEX Save on the same page" failed in all four verticals before this
change (`409 The model changed since this page loaded`). `syncTokens` brought the hidden inputs and the workbook
shell forward but only the swapped sheet's `v2-cost-authority-*` element received new attributes, and `liveTokens`
read the first authority element. The same stale read made "staged OPEX Save, then staged CAPEX Save" fail. That would
have made staged-by-default unsafe. Fixed in two places: `syncTokens` updates every authority element, and
`liveTokens` reads the workbook shell first. No token is ever guessed or reused after a failure.

## 4. UX changes

* Batch editing is the default for every editable cost line (Solar, Wind, Data Center, EV Charging; CAPEX and OPEX).
  Unticking "Save edits together" selects the immediate per-row mode, remembered for the tab.
* Enter commits a cell and moves down; Shift+Enter up; Tab / arrows navigate; **Esc discards only the current cell
  edit**; the stage bar's Discard drops everything; `Ctrl+S` saves.
* Staged rows are marked, the bar shows `N staged · M editing`, and sticks below the sticky header while edits exist.
* One deliberate Save sends one atomic request for CAPEX and OPEX rows together. Success and failure are visible; a
  failure keeps every typed value, marks the rows, and is never retried.
* A Run or a scenario switch with unsaved edits shows a Save / Discard / Stay notice in the panel being viewed.
  Nothing is saved or dropped silently. `beforeunload` still guards leaving the page.
* Focus and scroll: after a mouse Save, focus returns to the cell being edited; a keyboard Save keeps focus.
* Inputs Grid: categories whose total comes from line items link to the owning category on the cost sheet.

## 5. Existing functions reused

`update_cost_lines_batch` and `POST /v2/workbook/grid/cost-lines/save` (CSRF, owner / project / reference guards,
composite CAS, `row_version`, atomic rollback); `_render_capex_sheet_with_oob` / `_render_opex_sheet_with_oob`;
`commitRow`, `saveStaged`, `finishBatch`, the swap-view restore, `v2CostGridWhenIdle`; the Inputs Grid
`[data-nav-tab]` handler; the consolidated tab navigation. No second writer, no new endpoint.

## 6. Auto-compute versus Manual Run — investigated, not implemented

Manual Run is unchanged and no inert toggle is shown. Run is `POST /v2/workbook/run`: bound to the composite hash,
it runs the canonical engine through the bounded model executor (admission gate, `MODEL_EXECUTION_BUSY`), commits with a
second CAS (`v2_atomic_run_commit`, `V2RunCommitConflictError`) and writes an immutable Run History row. An honest
Auto-compute would need, at least:

1. an explicit per-project opt-in (default off), shown wherever it is active;
2. a rule that it never runs while edits are staged or being typed, and runs only after a Save succeeded;
3. coalescing: a newer Save supersedes a pending or in-flight run, and a run that loses the commit CAS is reported as
   "result discarded, newer edits exist", never silently retried;
4. defined behaviour on `MODEL_EXECUTION_BUSY` and on engine failure (no retry loop, visible state);
5. a visible state machine Saving → Running → Current / Stale that is accessible and does not move focus;
6. a decision on Run History volume, because every automatic run is an immutable record;
7. acceptance tests against the real executor: edit during run, busy, failure, double Save, scenario switch.

Until those are specified and tested, Manual Run stays the only way to run.

## 7. Verification

`tests/test_cost_editing_ux_v2_browser.py` (real Chromium, Solar / Wind / Data Center / EV where it matters):
batch default; four OPEX edits and ten mixed edits are one request with exact stored values and no network write
before Save; no duplicate Save; the stale-authority defect in both directions; explicit immediate mode and its
persistence; keyboard-only editing with cell-level Esc and `Ctrl+S`; invalid input blocks the Save without losing
values; stale composite hash and stale row version rejected with full rollback and no retry; foreign line, unknown
project and protected reference refused; scenario switch and Run guarded; tab marker; scroll and focus retention
(keyboard and mouse, both sheets); light and dark contrast ≥ 4.5; 390 px; Inputs Grid link focuses the category and
offers no editor. Save never runs the model and never writes Run History. The existing batch, grid-editing,
hybrid-grid, workspace and Workflow C browser suites pass; those that exercise the immediate path now select it
explicitly. Server-side atomicity, CAS, ownership and parity stay covered by `tests/test_cost_batch_save_v1.py`.

## 8. Limitations

* Figures are local and synthetic. They show request counts and relative latency, not staging performance.
* A single edited cell now needs one explicit Save (Ctrl+S) where it used to save on leaving the row. Immediate mode
  remains one click away and is remembered for the tab.
* A genuine 409 still keeps the typed values but needs a reload to obtain fresh tokens (no silent retry).
* Add / duplicate / deactivate / reactivate / reorder remain single commands and are refused while edits are staged.
* Cost line routes outside the batch endpoint still have no CSRF token (pre-existing, disclosed on `/trust/known-gaps`).
