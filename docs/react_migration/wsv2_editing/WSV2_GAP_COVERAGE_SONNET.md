# WS-2 gap coverage (M-001 … M-027)

Status vocabulary: IMPLEMENTED (source + tests) · PARTIAL · OWNER_GATE · PARTNER (WS-1) · VERIFY_ONLY · NOT_THIS_IMPLEMENTATION. Browser/staging acceptance is **not** claimed for any row.

| ID | Owner | Status | Evidence / note |
|---|---|---|---|
| M-007 | WS-2 | IMPLEMENTED (source) | `editing/grid.ts`, `useGridKeys.ts`, `CostLinesGridView.tsx`; 20 node tests. Not mounted until the shell integration patch (`SHARED_FILE_INTEGRATION.md`). Layout is provisional: the Owner put the final CAPEX/OPEX layout on hold pending the Excel comparison. |
| M-008 | WS-2 | PARTIAL + OWNER_GATE | Pending-change store, provider, Changes drawer, per-field/section Undo, Discard All, conflict markers, one-request builder: implemented and tested. **Atomic Save All endpoint: gated** — `SAVE_ALL_TRANSACTION_DESIGN.md`, `PROTECTED_PATH_REQUEST_SAVE_ALL.md`. UI shows BLOCKED. |
| M-009 | split | PARTIAL (editor side) | Drawer/badge/provider exports ready; layout slot is WS-1's. |
| M-010 | WS-2 | IMPLEMENTED (source) | Persistent per-row `State`/`Notes` columns removed in the new grid; notes behind a disclosure, data preserved; line sum is labelled "not a model result". Technology-specific line taxonomy is server-projected and untouched; no Solar names are hard-coded in the new grid. |
| M-013 | WS-2 | IMPLEMENTED (source), live in `PPAEditorView` | Percent inputs for volume share and annual indexation, exact decimal shift, `2↔0.02`, `100↔1`, 10 001-step round trip test, locale/ambiguity handling; identity/source reference moved to Advanced (new contracts get a generated id and the source "Entered in FINCO workspace"); existing stored values and preserved keys untouched. |
| M-004, 005, 006, 011, 012, 016, 020, 027 | WS-1 | PARTNER | not touched |
| M-009 layout | WS-1 | PARTNER | not touched |
| M-001, 002, 014, 015, 023, 024 | Financial Owner | OWNER_GATE / NOT_THIS_IMPLEMENTATION | no financial source touched |
| M-003, 018, 019, 021, 022, 026 | acceptance | VERIFY_ONLY | not claimed |
| M-017, 025 | Legacy | NOT_THIS_IMPLEMENTATION | untouched |

## Known follow-ups (honest limits)

1. **Committed bundle not rebuilt.** `static/react/finco-react.js` is byte-pinned in several governance layers; rebuilding needs the governed re-pin (as PR #396). Done once, at integration, after WS-1.
2. **Pinned browser acceptance** (`model_react_wf2_browser_acceptance.py`, `model_react_mvp_acceptance.py`) drive the PPA form with decimal ratios and the old labels ("Contracted volume share", "Indexation rate"). They will fail against the new UI until an Owner-authorised successor updates them; they are byte-pinned and not edited here.
3. **Browser tests of the new grid/drawer** (1440/1366/tablet/mobile screenshots, accessibility, two-tab conflict) require the shell mount and a running server; not done.
4. **Four governance tests fail identically on pristine `main`** in this sandbox (`test_rcux_governance` ×3, `test_fin_v2_pr394_corr_scope` ×1); no new failures introduced.
5. Draft restore after reload is deliberately absent (design §5).
