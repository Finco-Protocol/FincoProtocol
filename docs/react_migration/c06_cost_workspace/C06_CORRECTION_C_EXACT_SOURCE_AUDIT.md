# C06 Correction C — Exact-Source Audit (C + Addenda C1 + C2, one integration push)

## 1. Live preflight (performed at work start, refreshed during the session)

- accepted `main`: `b1c08e2d00fe9933565d253d5cee6e5849b143e1` (tree `5b25c1f245d3d53d9bbe24060c13dc936e06b8d7`) — unchanged during the session.
- #444 Draft HEAD at preflight: `6eae95cd74ef78b732c275e50d1dbeef0b93f299` (tree `3d073dd7ba424ea5b5f01e2e979c4e47e9efe3bd`), base = the same `main`, `mergeable: true`.
- Six workflows at that HEAD: Governance Full History `43242867712` PASS, Dependency Security Audit `43242867458` PASS, Compile and Safety `43242867584` PASS, FIN-VAL F01 `43242867491` PASS, Browser `43242867598` FAIL (job `131268169263`), CI V4 `43242868047` in progress (plan/static/f01 passed; shards running).
- This correction works ON TOP of that HEAD; no rebase, no squash, no force-push.

## 2. Changed paths and exact blobs (Correction C + C1 + C2)

All blobs are Git blob SHA-1 over the committed bytes. `BASE` = accepted `main`.

| path | base blob | final blob (this push) | change |
|---|---|---|---|
| `frontend/src/app/plainCopy.ts` | `a07f35a3…` (at BASE) | see manifest | product-truth hint guard (Correction C) |
| `frontend/src/app/editing/CostLinesGridView.tsx` | `860a5310…` | see manifest | month-window nav, unit-labelled timeline note/headers (C2) |
| `frontend/src/app/capex/CapexStudio.tsx` | at BASE | see manifest | Expanded monthly view (collapsed) with Copy/CSV + kEUR headers + rounding note (C2) |
| `frontend/src/app/CostWorkbench.tsx` | at BASE | see manifest | Monthly-schedule note points at the Expanded monthly view (C2) |
| `frontend/src/styles/rx-mvp-correction.css` | at BASE | see manifest | `.rx-input-table` cells `overflow-wrap: anywhere → break-word` (C1) |
| `frontend/src/styles/compact-inputs.css` | at BASE | see manifest | `.ci-summary-table` row labels `break-word`; `.ci-tl-nav`/`.ci-expanded-monthly` styles (C1+C2) |
| `static/react/finco-react.js` | `36b69ce9…` | see manifest | deterministic rebuild (`npm run build`, vite 5.4.11, React 18.3.1) |
| `static/react/finco-react.css` | `f3aa0c98…` | see manifest | deterministic rebuild (C1/C2 styles) |
| `tests/test_c06_cost_workspace_browser.py` | `ae25712f…` | see manifest | +3 source-bound browser tests (C both-timings, C1 geometry, C2 nav/units/expanded view) |
| `tests/model_react_rcux_capex_acceptance.py` | at BASE | see manifest | expanded-view opt-in folded into the existing matrix assertions (no assertion weakened) |
| `tests/u2_scope.py` | `fa1b1cfc…` (BASE) | see manifest | `_c06_pin`/`supersedes` Correction C path extension (bounded hook, Correction B pattern) |
| `tests/u1_scope.py` | `288b77d9…` (BASE) | see manifest | `_c06_correction_c_pin` bounded hook in the pin comparison (Correction C) |
| `tests/c06_cost_workspace_scope.py` | self | see manifest | successor contract: SOURCE_PATHS/HANDOFF_PATHS/HANDOFFS/APPROVED_SOURCE_BLOBS extended; `finco-react.css` unfrozen as a reviewed owned path |
| `docs/react_migration/c06_cost_workspace/SOURCE_SUCCESSOR.json` | self | see manifest | canonical successor manifest (47 owned, 41 base, modes 100644) |
| `docs/ci_v4/SOURCE_SUCCESSOR.json`, `docs/react_migration/post413_o1/…`, `post413_r1/…`, `u2_workbench/U2_EXACT_SOURCE.json` | moved keys only | see manifest | `finco-react.js`/`u2_scope.py` MAP_KEYS pins moved to the exact new blobs (only MAP_KEYS keys moved; no other key changed) |

Exact per-file blob values are recorded canonically in
`docs/react_migration/c06_cost_workspace/SOURCE_SUCCESSOR.json` (single source of truth;
`git rev-parse BASE:path` verifies every base blob).

## 3. Successor proof (verified locally, reproduced by CI)

- `tests.c06_cost_workspace_scope.signature_ok` = **True**, `exact_blobs_ok` = **True** on the
  working tree at this commit (steps walked one-by-one: self-pin, APPROVED set/values, pin sets,
  modes, judged snapshot, HANDOFFS expectations, CURRENT_MAPS expectations, FROZEN integrity).
- Handoff coherence: `tests/u2_scope.py` and `tests/u1_scope.py` bytes equal exactly
  `expected_handoff(BASE + reviewed substitutions)`; their pins equal their bytes.
- Admission chains: `u2._c06_pin`/`u1._c06_correction_c_pin` admit exactly the Correction C
  moved pins only while the C06 tip cohort is exact (`C06.signature_ok ∧ C06.supersedes`),
  matching the bounded Correction B pattern. Historical manifests untouched; every base blob
  re-verified against `git rev-parse BASE:path`.
- Negative controls: the parametrized worktree tamper test (`test_worktree_byte_tamper_fails_without_changing_head`)
  now covers every newly owned path, including `frontend/src/app/plainCopy.ts`.

## 4. Frozen/historical integrity

- All FROZEN paths except the explicitly reviewed `static/react/finco-react.css` are
  byte-identical to BASE (asserted by the signature step and by `test_literal_closed_paths_and_immutable_predecessor_blobs`).
- `finco-react.css` was frozen only because Correction B shipped no CSS change; Correction C's
  reviewed C1 remedy moves it as an owned path with its exact new pin (recorded above).
- No `.github/`, `financial_engine/`, `finco_core/`, `domain/`, `tools/`, `migrations/`,
  `app/` or `research/` path is touched by this push.

## 5. Negative tests delivered

1. `test_inputs_product_truth_holds_in_both_editor_timing_orders` — the product-truth scan
   must hold **before and after** the async editor mounts (the exact hosted flake window).
2. `test_assumptions_labels_wrap_at_word_boundaries_never_one_character` (1440/390) —
   `overflow-wrap == 'break-word'`, `table-layout: fixed`, label width ≥ 100px, height ≤ 90px,
   no page overflow. Pins the C1 mechanism (`anywhere` min-content collapse) out of the product.
3. `test_capex_month_navigation_unit_labels_and_expanded_monthly_view` — month-window nav
   (`data-tl-nav`), `M… of M…` indicator advancing on `Next months`, sticky `ci-col-line`,
   unit-labelled note/headers, month cells staying the exact server text; Expanded monthly
   view collapsed by default with Copy/CSV inside and `Total (kEUR)` headers.
4. Existing governance tamper suite (clone-based) extended by the new owned paths automatically.
